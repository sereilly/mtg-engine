from __future__ import annotations

import re

from ..card_hooks import ON_LEAVE_BATTLEFIELD
from ..auras import auras_attached_to, detach_aura
from ..control import (
    base_controller,
    change_control,
    control_changes,
    end_control_change,
    has_control_change,
    set_base_controller,
)
from ..delayed_triggers import fire_delayed_triggers
from ..events import emit
from ..layer_bridge import computed_controller
from ..land_types import end_land_type_change
from ..linked_exile import LEAVES, UNTAPPED
from ..models import Permanent, PlayerState, next_permanent_id
from ..game_types import GraveyardTarget
from ..oracle import compile_card_oracle
from ..replacements import apply_entry_riders, apply_replacements
from ..regeneration import regeneration_replaces_destruction
from ..targeting import graveyard_target_spec
from ..tokens import CREATED_WITH_PERMANENT_ID, is_token_card
from ..trigger_utils import make_trigger_event, matching_triggers
from ._constants import _MANA_SYMBOLS, _NO_PRIORITY_STEPS

# The dies-triggers ``_permanent_to_graveyard`` carries out **inline** rather
# than putting on the stack, each for the reason its own block there gives: the
# life loss is part of the state-based sweep, the token is an obligation the
# source outlives, and the combat relationship is unreadable a line later. They
# are named here rather than tested for one at a time, so the general enqueue
# beside them is "everything else" — a set that can be read, instead of a
# sequence of loops whose gaps only show up as a card doing nothing.
_INLINE_DIES_KINDS = frozenset({
    "owner_loses_half_life",                    # Personal Incarnation
    "destroy_creatures_in_combat_with_source",  # Abu Ja'far
})


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

    def record_reveal(self, player_index: int, card_names: list[str]) -> None:
        """Record that *player_index* revealed *card_names* to all players
        (CR 701.20). The prose log already names revealed cards; this is the
        structured record beside it, read by the web layer so a client can show
        the revealed faces. One entry per reveal — a Cultivate that finds two
        cards is one event, not two — and only the newest few are kept, because
        a client diffs the feed by id rather than replaying a history."""
        if not card_names:
            return
        self.reveal_event_seq += 1
        self.reveal_events.append({
            "id": self.reveal_event_seq,
            "seat": player_index,
            "cards": list(card_names),
        })
        del self.reveal_events[:-10]

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
            for bucket in player.restricted_mana.values():
                bucket.clear()

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
                self.remove_from_battlefield(attached)
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

    def cant_gain_control(self, permanent: Permanent, seat) -> bool:
        """Whether *seat* is forbidden right now to gain control of *permanent*.

        Guardian Beast: "As long as this creature is untapped, noncreature
        artifacts you control ... **other players can't gain control of
        them**." CR 614.17 - a "can't" is not a replacement effect but follows
        the same rules, and the rule this one states is about the *gaining*,
        never about which sentence does the gaining.

        Which is why it lives on the seam rather than in one handler. Exactly
        one asked it - the artifact-only linked steal - so Gauntlets of Chaos
        and Juxtapose exchanged a protected artifact away and Magus of the
        Unseen borrowed one, all three with the Beast untapped and nothing
        failing. A list of the handlers that move control is the fire-site list
        this codebase keeps finding incomplete.

        "**Other** players": a permanent's own controller re-recording control
        of it is not a gain, so the seats are compared first.
        """
        holder = self.controller_index_of(permanent)
        if holder is None or holder == self.seat_index(seat):
            return False
        return self._untapped_artifact_protector_active(permanent)

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
        # CR 614.17's prohibition, asked at the one place a steal records its
        # contribution rather than in each steal handler (see
        # :meth:`cant_gain_control`).
        if self.cant_gain_control(permanent, seat):
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
            # NOT a removal, and deliberately not routed through
            # `remove_from_battlefield`: this is a *move* between two
            # battlefields, the projection of a derived controller change (CR
            # 613 layer 2). The permanent does not leave the battlefield, so
            # anything hung off the leave transition — dies triggers, Aura
            # cleanup, the combat remap this choke point exists to host — must
            # not fire here. The pair of statements is one operation and is
            # written open so that is visible.
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

    def phase_out_permanent(self, permanent: Permanent) -> bool:
        """CR 702.26: *permanent* phases out, its attached Auras with it.

        Not a zone change (702.26b): no leave-the-battlefield or dies event
        fires, the object keeps its id and state, and it returns as the same
        object at its controller's untap step. ``remove_from_battlefield`` is
        used for the list mechanics because it is the transition that keeps
        the combat maps renumbered; where the permanent goes next — the
        controller's ``phased_out`` holding list — is this caller's business.
        """
        controller = self.controller_index_of(permanent)
        if controller is None:
            return False
        moving = [permanent] + [
            aura
            for aura in list(permanent.metadata.get("attached_auras") or [])
            if self.is_on_battlefield(aura)
        ]
        self.remove_all_from_battlefield(moving)
        for perm in moving:
            perm.metadata["phased_out"] = True
            self.players[controller].phased_out.append(perm)
            self.log.append(f"{perm.card.name} phased out")
        self._recompute_continuous_effects()
        return True

    def phase_in_for(self, seat: int) -> None:
        """CR 702.26e: phased-out permanents *seat* controls phase in as its
        untap step begins — the same object, no new permanent_id, no
        enters-the-battlefield anything. A ``phase_in_blocked`` marker
        (Teferi, Timeless Voyager's rider) holds a permanent out until its
        countdown expires."""
        player = self.players[seat]
        if not player.phased_out:
            return
        staying: list[Permanent] = []
        for perm in player.phased_out:
            block = perm.metadata.get("phase_in_blocked")
            if isinstance(block, dict) and int(block.get("turn_ends_remaining", 0)) > 0:
                staying.append(perm)
                continue
            perm.metadata.pop("phased_out", None)
            perm.metadata.pop("phase_in_blocked", None)
            player.battlefield.append(perm)
            self.log.append(f"{perm.card.name} phased in")
        player.phased_out = staying
        self._recompute_continuous_effects()

    # -- the two zones CR 903.9b intercepts ---------------------------------
    #
    # Every "put this card into a hand / a library" in the engine goes through
    # one of these two. That is not tidiness: CR 903.9b is a replacement over an
    # event with no single fire site — a bounce, a tuck, a regrowth and a draw
    # are all "would be put into its owner's hand or library from anywhere" —
    # and a rule with thirty possible fire sites is a rule twenty-nine of them
    # forget. Outside a Commander game both are a plain append, so nothing else
    # changes shape.

    def _owner_seat(self, owner) -> int:
        """A seat index from either a seat index or a ``PlayerState``. Both
        spellings reach these two seams from call sites that already hold one or
        the other, and converting at the boundary is cheaper than making every
        caller convert."""
        return owner if isinstance(owner, int) else self.players.index(owner)

    def take_card_from_hand(self, owner, card) -> bool:
        """Remove **one** copy of *card* from *owner*'s hand. True if it was there.

        The mirror of ``put_card_into_hand``, and it exists because the obvious
        spelling is wrong. A hand is a ``list[CardDefinition]`` and a deck is
        built by repeating one definition — ``deck.extend([card] * count)`` in
        ``web/deck_builder.py``, and the same in the AI simulator — so every
        copy of a card in a hand is *the same Python object*. That makes
        ``player.hand = [c for c in player.hand if c is not card]`` remove all
        of them, and the caller then puts exactly one somewhere: the rest cease
        to exist.

        ``engine/phases/upkeep_step.py`` documents the same bug found in a
        graveyard (Nether Shadow: five cards in, four out) and fixed there by
        carrying the index. Five more sites had it in hands — Sylvan Library's
        "put the card on top of your library", a forced discard, two discard
        costs and a put-onto-the-battlefield — all invisible until a deck held
        two copies of one card *and* one of those effects fired. The AI
        simulator's fixed eight-card decklist could reach neither half.

        Removing by index is what makes it exactly one, and identity is what
        picks the index: ``list.remove`` and ``list.index`` compare by value,
        which on a frozen dataclass means two different printings of one card
        would match each other.
        """
        player = self.players[self._owner_seat(owner)] if isinstance(owner, int) else owner
        for index, held in enumerate(player.hand):
            if held is card:
                del player.hand[index]
                return True
        return False

    def put_card_into_hand(self, owner, card) -> bool:
        """Put *card* into its owner's hand, unless CR 903.9b diverts it.

        Returns True when the card actually arrived. False means it was a token
        and ceased to exist (CR 111.7), it went to the command zone instead, or
        it is waiting on its owner's answer and is in no zone until then — in
        every case the caller must not also record a card arriving in hand.
        """
        seat = self._owner_seat(owner)
        if is_token_card(card):
            return False  # CR 111.7 / 704.5d: it ceases to exist instead
        if self.commander_zone_change(seat, card, "hand"):
            return False
        self.players[seat].hand.append(card)
        return True

    def put_card_into_library(self, owner, card, position: str = "bottom") -> bool:
        """Put *card* into its owner's library, unless CR 903.9b diverts it.
        ``position`` is "top" or "bottom"; the return value reads as
        :meth:`put_card_into_hand`'s does."""
        seat = self._owner_seat(owner)
        if is_token_card(card):
            return False  # CR 111.7 / 704.5d: it ceases to exist instead
        if self.commander_zone_change(seat, card, "library"):
            return False
        library = self.players[seat].library
        if position == "top":
            library.insert(0, card)
        else:
            library.append(card)
        return True

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
            if not permanent.metadata.get("is_token", False):
                self.nontoken_creatures_died_this_turn = (
                    getattr(self, "nontoken_creatures_died_this_turn", 0) + 1
                )
            # "…under your control" is a different question from the game-wide
            # count above, and only the controller can answer it. `player` is
            # the controller the permanent last had; the owner is looked up
            # separately precisely because the two differ under Control Magic.
            player.creatures_died_under_your_control_this_turn += 1
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
            # **Every other** "when this creature dies" trigger, onto the stack
            # (CR 603.3). One loop, not one per instruction kind.
            #
            # This was six loops, each keyed to the kind of the card that added
            # it — ``may`` for Goblin Arsonist, ``target_gains_life`` for
            # Conclave Mentor, and so on — and the answer to "what happens when
            # a creature with a dies-trigger this engine has not met before
            # dies?" was *nothing at all*. Onulet ships in the shipped pool at
            # 388/388, marked verified: "When this creature dies, you gain 2
            # life", and no life was ever gained, because its instruction kind
            # was `target_gains_life` without Conclave Mentor's payload key. A
            # fire site that enumerates instruction kinds cannot be complete;
            # it can only be as complete as the last card that touched it.
            #
            # ``dead_power`` is captured for every trigger whether or not it
            # asks: the permanent is about to leave and CR 603.10 says the
            # trigger uses the information the game had, so the read has to be
            # here even though only some payloads consume it.
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"dies"},
            ):
                if trig.instruction is None or trig.instruction.kind in _INLINE_DIES_KINDS:
                    continue
                self._enqueue_triggered_ability(
                    controller_index=self.players.index(player),
                    source_permanent=permanent,
                    card=permanent.card,
                    instruction=trig.instruction,
                    effect_kind=trig.effect_kind,
                    ability_text=trig.source_line,
                    trigger_context={"dead_power": max(0, permanent.effective_power)},
                )
                self.log.append(f"{permanent.card.name} triggered (died)")
        text = permanent.effective_card.oracle_text.lower()
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
        self._fire_permanent_dies_triggers(permanent)
        # "When that creature dies this turn, …" (Reincarnation). A delayed
        # ability (CR 603.7) belongs to no permanent, so neither of the scans
        # above can reach it — and this is the seam every death already passes
        # through. The owner's seat rides the context because CR 603.10 says
        # the ability uses the information the game had: by resolution the card
        # is in a graveyard, which has no controller and cannot say whose
        # battlefield it left.
        fire_delayed_triggers(
            self, "bound_permanent_dies", subject=permanent,
            trigger_context={
                "event_subject_owner": self.owner_index_of(permanent),
                "event_subject_controller": self.controller_index_of(permanent),
                "dead_name": permanent.card.name,
            },
        )

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
        # The subject's controller, frozen into the announcement (CR 603.10).
        # "…deals 2 damage to **that land's controller**" (Psychic Venom) is a
        # back-reference to the object this event is about, and the seat has to
        # come from here: by resolution the trigger has only a resolution
        # context, whose player slot is whatever a targetless resolution
        # defaults to. Stamped for both emits below because a card printing the
        # phrase can hang off either event.
        tapped_seat = self.controller_index_of(permanent)
        emit(
            self, "permanent_becomes_tapped",
            subject=permanent, event_subject_controller=tapped_seat,
            # The tapped object itself, by id (CR 400.7 — an index is not an
            # identity). A trigger that acts *on* it rather than on its
            # controller ("destroy it" — Kudzu) reads it here, frozen at the
            # announcement, because by resolution the land may have moved and a
            # board search would find a look-alike.
            event_subject_permanent_id=permanent.permanent_id,
        )
        # "Whenever an artifact becomes tapped **or** a player activates an
        # artifact's ability without {T} in its activation cost" (Haunting
        # Wind, Powerleech) — one printed ability with two trigger events, so
        # one condition kind announced from both. This is the tapping half; the
        # other is in stack/activation.py, where an ability whose cost has no
        # {T} finishes paying.
        emit(
            self, "permanent_tapped_or_ability_activated",
            subject=permanent, event_subject_controller=tapped_seat,
        )
        return True

    def playable_card_of(self, permanent: "Permanent"):
        """*permanent*'s effective card, plus any abilities granted by the card
        on top of its controller's library (Conspicuous Snoop).

        Not folded into ``Permanent.effective_card``: that is a property with no
        game to ask, and the grant's source is not a permanent at all but a card
        in a *zone* — one that changes on every draw, so a stamped answer goes
        stale where a derived one cannot. Asked here, where the game is, by the
        two callers that need it: the activation path and the ability listing
        the UI reads.
        """
        from ..library_top import granted_top_abilities
        from ..models import _with_granted_abilities

        base = permanent.effective_card
        granted = granted_top_abilities(self, permanent)
        return _with_granted_abilities(base, granted) if granted else base

    def become_untapped(self, permanent: "Permanent") -> bool:
        """Turn *permanent* from tapped to untapped, firing "becomes untapped"
        triggers (CR 701.26b). Returns whether it actually changed.

        The twin of :meth:`become_tapped`, and it exists for the same reason
        that one does: ``perm.tapped = False`` was written in eleven places, so
        a "becomes untapped" trigger could only ever see whichever of them its
        implementer happened to wire into. Ghostly Pilferer is the first card in
        the pool to ask, and it would otherwise have fired on the untap step
        alone — not on Twiddle, not on its own controller's untapper, not on any
        of the nine other ways a permanent untaps.

        CR 701.26b: only a tapped permanent can be untapped, so re-untapping is
        no state change and no trigger. A permanent *entering* untapped never
        becomes untapped either — it was never tapped on the battlefield — which
        is why the entry path does not come through here, exactly as it does not
        come through ``become_tapped``.
        """
        if not permanent.tapped:
            return False
        permanent.tapped = False
        emit(self, "permanent_becomes_untapped", subject=permanent)
        # "When this creature leaves the battlefield **or becomes untapped**,
        # destroy that creature." (Merieke Ri Berit.) The second of the two
        # events one delayed ability answers to, announced here for the reason
        # the linked-exile return below is: this is the one place a permanent
        # becomes untapped, so an announcement wired into any single untapper
        # would be one the other ten forgot.
        fire_delayed_triggers(
            self, "bound_permanent_leaves_or_untaps", subject=permanent,
        )
        # "When this artifact leaves the battlefield **or becomes untapped**,
        # return that exiled card…" (Tawnos's Coffin). The second of the two
        # things that end a linked exile, and it is here for the reason the
        # first is in `remove_from_battlefield`: this is the one place a
        # permanent becomes untapped, so a return wired into any single untapper
        # would be a return the other ten forgot.
        self.return_linked_exile(permanent, "became untapped", UNTAPPED)
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

    # ------------------------------------------------------------------
    # Addressing one permanent (CR 400.7)
    #
    # The seam above answers "which permanents"; this answers "*that* one".
    # Both questions used to be answered by opening ``player.battlefield``, and
    # the second one was answered *positionally* — ``player.battlefield[i]`` —
    # which is unstable by construction: anything leaving the battlefield
    # renumbers every later slot, so an index held across a resolution step
    # addresses a different permanent than the one it was taken for.
    #
    # ``Permanent.permanent_id`` is the stable answer, and these are the only
    # places that turn one into a permanent. Scattering the lookup would put
    # the same bounds-checking and the same "it may be gone by now" decision in
    # every caller, which is how the positional reads spread in the first place.
    # ------------------------------------------------------------------

    def permanent_by_id(self, permanent_id) -> "Permanent | None":
        """The battlefield permanent with this id, or None if it has left.

        None is the answer a caller wants: a permanent that is gone is *gone*,
        where ``battlefield[i]`` would hand back whichever permanent slid into
        that slot. Callers should treat None as "the target is no longer there"
        (CR 608.2b), not as an error."""
        found = self.find_permanent_by_id(permanent_id)
        return None if found is None else found[1]

    def find_permanent_by_id(self, permanent_id) -> "tuple[int, Permanent] | None":
        """``(controller seat, permanent)`` for this id, or None if it has left.

        The paired form, for the callers that need the seat as well — the seat
        is *derived* here rather than remembered by the caller, so a permanent
        that changed control since the id was taken resolves to whoever
        controls it now (CR 613 layer 2)."""
        if permanent_id is None:
            return None
        try:
            wanted = int(permanent_id)
        except (TypeError, ValueError):
            return None
        for seat, permanent in self.permanents_with_controller():
            if permanent.permanent_id == wanted:
                return seat, permanent
        return None

    def permanent_id_of(self, permanent: Permanent) -> int | None:
        """*permanent*'s stable id while it is on the battlefield, else None.

        None for a permanent that has left, so an id taken from here is always
        one ``permanent_by_id`` can still resolve — by identity, because a
        look-alike's id is a different number and asking by value would find
        it."""
        if permanent is None or not self.is_on_battlefield(permanent):
            return None
        return permanent.permanent_id

    def battlefield_index_of(self, permanent: Permanent) -> int | None:
        """*permanent*'s slot on its controller's battlefield, or None.

        **The bridge, not the destination.** The wire protocol still addresses
        a permanent by index, so the payload has to carry one until the client
        has finished migrating; this is where that index is derived, by
        identity, instead of each serializer running its own ``enumerate``."""
        seat = self.controller_index_of(permanent)
        if seat is None:
            return None
        for index, candidate in enumerate(self.controlled_by(seat)):
            if candidate is permanent:
                return index
        return None

    def permanent_at(self, seat, index) -> "Permanent | None":
        """The permanent in *seat*'s battlefield slot *index*, or None.

        The other half of the bridge: an index arriving from the wire has to be
        turned into a permanent exactly once, at the boundary, and then carried
        as an id. Bounds-checked, because every open-coded
        ``0 <= i < len(battlefield)`` guard is one that can be forgotten."""
        if index is None:
            return None
        try:
            wanted = int(index)
        except (TypeError, ValueError):
            return None
        if wanted < 0:
            return None
        battlefield = list(self.controlled_by(self.seat_index(seat)))
        if wanted >= len(battlefield):
            return None
        return battlefield[wanted]

    def chosen_permanent(self, seat, index, permanent_id) -> "Permanent | None":
        """The permanent a cast-time choice named, preferring its stable id.

        The read half of what ``_stack_push`` writes. A spell records both when
        its target is chosen (CR 601.2c) and resolution asks for both here, so
        the id answers whenever it still can and the index answers exactly as it
        always did when it cannot.

        **Additive on purpose.** Falling through to the index rather than
        failing means this can only turn a wrong answer into a right one: a
        target that has left the battlefield behaves as before (whatever slid
        into its slot, or nothing), rather than acquiring a fizzle the callers
        are not yet written for. Tightening that into a CR 608.2b refusal is a
        behaviour change and belongs in a change that says so.

        Scoped to *seat* like the index it replaces, so a permanent that changed
        controller is not silently still targeted from its old side.
        """
        if isinstance(permanent_id, int):
            found = self.permanent_by_id(permanent_id)
            if found is not None and self.controls(seat, found):
                return found
        return self.permanent_at(seat, index)

    # -- The same question one zone over -----------------------------------
    #
    # A graveyard slot is as unstable as a battlefield slot and has no id to
    # fall back on, so the four functions below are `permanent_id_of` /
    # `permanent_by_id` / `chosen_permanent` rewritten for a zone whose objects
    # cannot be told apart by identity at all.

    def graveyard_target_at(self, seat, index):
        """Name the card in *seat*'s graveyard slot *index*, or None.

        The write half. ``ordinal`` counts how many *earlier* slots hold the
        same ``CardDefinition`` object, which is the only thing that separates
        two copies of one card once the dedupe has made them one object.
        """
        if seat is None or not 0 <= seat < len(self.players):
            return None
        graveyard = self.players[seat].graveyard
        if not isinstance(index, int) or not 0 <= index < len(graveyard):
            return None
        card = graveyard[index]
        ordinal = sum(1 for other in graveyard[:index] if other is card)
        return GraveyardTarget(seat=seat, card=card, ordinal=ordinal)

    def graveyard_index_of(self, target) -> int | None:
        """Where *target* sits in its graveyard **now**, or None when no copy of
        that card is there any more.

        The read half. Clamps to the last surviving copy rather than failing
        when fewer copies remain than the ordinal asked for: with two copies of
        one card the engine cannot know *which* one left, because they are the
        same object, so the choice is between two indistinguishable answers and
        the one that keeps the two copies behaving alike is the honest one.
        "Gone" is reserved for the case the data model can actually establish —
        no copy of that card left in that graveyard.
        """
        if target is None or not 0 <= target.seat < len(self.players):
            return None
        graveyard = self.players[target.seat].graveyard
        positions = [i for i, card in enumerate(graveyard) if card is target.card]
        if not positions:
            return None
        return positions[min(target.ordinal, len(positions) - 1)]

    def chosen_graveyard_index(self, target, index):
        """The graveyard slot a cast-time choice named, re-located now.

        Additive for the same reason ``chosen_permanent`` is: a stamp that no
        longer resolves falls through to the index the caller already had, so
        this can only turn a wrong answer into a right one. Mirrors the shape it
        is given — one slot, a list of them, or None.
        """
        if isinstance(target, list):
            slots = index if isinstance(index, list) else []
            return [
                self.chosen_graveyard_index(stamp, slots[i] if i < len(slots) else None)
                for i, stamp in enumerate(target)
            ]
        found = self.graveyard_index_of(target)
        return index if found is None else found

    def stamp_graveyard_targets(self, seat, index):
        """Every chosen graveyard slot, named. Mirrors the index's own shape."""
        if isinstance(index, list):
            return [self.graveyard_target_at(seat, slot) for slot in index]
        return self.graveyard_target_at(seat, index)

    def graveyard_target_seat(self, item, spec: dict) -> int:
        """Whose graveyard a stack item's chosen index counts into.

        The same defaulting the resolution side does, in one place so the stamp
        and the reader cannot disagree: a spec that says ``own_graveyard_only``
        is always the caster's own zone (that flag is read off the *handler*,
        not off the printed words), and everything else follows the target
        player the item recorded, behind ``_stack_push``'s standing convention.
        """
        if spec.get("own_graveyard_only"):
            return item.caster_index
        seat = item.target_player_index
        if seat is None or not 0 <= seat < len(self.players):
            # **The caster's own**, not the opposing seat. The opposing default
            # is the *battlefield* convention — a spell naming a permanent and
            # no player usually means an opponent's — and it is backwards one
            # zone over, where the pile a spell reaches into is usually its own
            # caster's. It was a disagreement rather than a preference, too:
            # Animate Dead's cast validation checks the chosen index against the
            # caster's graveyard while `_apply_aura_effect` read it out of the
            # opponent's, so naming your own Grizzly Bears reanimated their
            # Shivan Dragon.
            seat = item.caster_index
        return seat

    def remove_from_battlefield(self, permanent: Permanent) -> Permanent | None:
        """Take *permanent* off the battlefield. The one transition out.

        Returns the permanent when it was there, None when it was not — so a
        caller that needs the object (most of the old ``battlefield.pop(idx)``
        sites did) gets it without a second lookup, and a caller that does not
        can ignore it.

        **Where it goes next is the caller's business.** A permanent leaves for
        a graveyard, exile, its owner's hand or library, or into the phased-out
        limbo an effect is holding it in, and those destinations have nothing in
        common. This does the one part they share.

        The reason it is one function is the reason ``become_tapped`` is one
        function. The battlefield was rebuilt or shortened in **41 places**, in
        three different spellings (filter-by-identity, ``pop`` by index, rebuild
        from a survivors list), and anything that has to happen when a permanent
        leaves therefore had 41 places to be wired into and 41 places to be
        forgotten. The live example is the one that motivated this: every combat
        map is keyed by battlefield index, so a permanent leaving mid-combat
        renumbers every attacker and blocker recorded after it, and there was no
        single place to put the remap.

        By **identity**, never by value: ``Permanent.__eq__`` compares by value,
        so ``list.remove`` and ``in`` match an opponent's look-alike card. That
        bug class is why ``.battlefield.remove()`` is banned outright by
        ``tests/engine/test_control_reads.py``.
        """
        removed = self.remove_all_from_battlefield((permanent,))
        return removed[0] if removed else None

    def remove_all_from_battlefield(self, permanents) -> list[Permanent]:
        """Take several permanents off the battlefield at once.

        The shape a sweep needs — destruction, a mass bounce, a player leaving
        the game — rebuilding each affected battlefield **once** rather than
        once per permanent. Returns those actually removed, in the order they
        sat on their battlefields, so a caller can log or process exactly what
        left.

        Not simply a loop over :meth:`remove_from_battlefield`, because a sweep
        that rebuilds per victim is quadratic and, worse, renumbers between
        victims — which is the failure the callers were open-coding around when
        they built a ``survivors`` list themselves.
        """
        targets = [perm for perm in permanents if perm is not None]
        if not targets:
            return []
        departing = {id(perm) for perm in targets}
        # Where each departing permanent sat, per seat, *before* the rebuild —
        # everything combat records is a slot on one of these lists, and once
        # the lists are rebuilt the old numbers are unrecoverable.
        vacated: dict[int, list[int]] = {}
        for seat, player in enumerate(self.players):
            gone = [i for i, perm in enumerate(player.battlefield) if id(perm) in departing]
            if gone:
                vacated[seat] = gone
        # "When this enchantment leaves the battlefield, you lose the game."
        # (Nine Lives.) CR 603.6c: a leaves-the-battlefield ability triggers
        # when a permanent moves from the battlefield to another zone, and
        # CR 603.10 makes what it sees the last-known information — so the seat
        # and the ability are read here, while the permanent is still on a
        # battlefield, and announced once the rebuild below is done.
        #
        # Announced from this one transition rather than from the zone-change
        # callers, for the reason the exile-return at the bottom of this
        # function gives: the other forty would forget it. It had no fire site
        # at all until round 140 — the condition parsed on both sides of the
        # pipeline and Nine Lives compiled a real `player_loses_game` under it —
        # and nothing reached the gap while the card's prevention was
        # unimplemented, because the enchantment never left the battlefield.
        from ..trigger_utils import make_trigger_event, matching_triggers

        # Paired with the permanent whose *leaving* announces it, which is not
        # always the event's source permanent: Dance of Many's second trigger
        # belongs to the enchantment and fires on the token's departure, so the
        # filter below has to ask about the token while the stack item names
        # the enchantment.
        leaving: list[tuple[Permanent, dict]] = []
        for perm in targets:
            seat = self.controller_index_of(perm)
            if seat is None:
                continue
            for trig in matching_triggers(
                perm.effective_card, condition_kinds={"leaves_battlefield"}
            ):
                leaving.append((perm, make_trigger_event(seat, perm, trig)))
            # "When **the token** leaves the battlefield, sacrifice this
            # enchantment." (Dance of Many.) The same CR 603.6c event about a
            # different object: the ability belongs to the permanent that
            # *made* this token, not to the token, so the scan above cannot
            # reach it — the token names its maker by id (CR 400.7 makes a
            # returning permanent a different one, and the id is what says so)
            # and the lookup is that one hop.
            #
            # Read here, before the rebuild, for the reason the scan above is:
            # by the time the batch is enqueued the maker may have left in the
            # same sweep, and its seat would be unaskable.
            creator = self.permanent_by_id(
                perm.metadata.get(CREATED_WITH_PERMANENT_ID)
            )
            creator_seat = (
                self.controller_index_of(creator) if creator is not None else None
            )
            if creator_seat is None:
                continue
            for trig in matching_triggers(
                creator.effective_card,
                condition_kinds={"created_token_leaves_battlefield"},
            ):
                # The **maker** is the source permanent: it is whose ability
                # this is, and "sacrifice this enchantment" would otherwise
                # sacrifice the token that just left.
                leaving.append(
                    (perm, make_trigger_event(creator_seat, creator, trig))
                )

        removed: list[Permanent] = []
        for player in self.players:
            if not any(id(perm) in departing for perm in player.battlefield):
                continue
            survivors = []
            for perm in player.battlefield:
                (removed if id(perm) in departing else survivors).append(perm)
            player.battlefield = survivors
        if removed:
            self._renumber_combat_after_removal(vacated)
        # Only for the permanents that were really there: `targets` is what the
        # caller asked about and `removed` is what left, and a trigger announced
        # for a permanent already off the battlefield would fire on nothing.
        departed = {id(perm) for perm in removed}
        self._enqueue_triggered_batch(
            [event for watched, event in leaving if id(watched) in departed]
        )
        # "…until this creature leaves the battlefield" (Kitesail Freebooter).
        # Here because this is the one transition out: a return wired into any
        # single caller would be a return the other forty forgot, which is the
        # reason this function exists at all.
        # "Exile that token **when Stangg leaves the battlefield**" (Stangg).
        # A delayed ability (CR 603.7) belongs to no permanent, so the scan
        # above cannot reach it, and CR 603.6c's event is any move off the
        # battlefield rather than a death — so it is announced here, from the
        # one transition every such move passes through, and not from the
        # graveyard path beside the dies-triggers.
        for perm in removed:
            fire_delayed_triggers(
                self, "bound_permanent_leaves_battlefield", subject=perm,
            )
            # "…leaves the battlefield **or becomes untapped**" (Merieke Ri
            # Berit). One ability answering to either event, so this site
            # announces the second key beside the first; `become_untapped` is
            # the other announcer. A separate call rather than a list of
            # aliases, because an entry armed under one key must not be woken
            # by the other's name.
            fire_delayed_triggers(
                self, "bound_permanent_leaves_or_untaps", subject=perm,
            )
        for perm in removed:
            self.return_linked_exile(perm, "left the battlefield", LEAVES)
        return removed

    def leave_linked_exile(
        self, entry: dict, zone: str
    ) -> "Permanent | None":
        """Take one linked-exile entry's card out of exile and into *zone*.

        The one placement both readers of the record share: the automatic
        return below, and the ``put_exiled_with_source`` handler that Knowledge
        Vault's two linked abilities compile to. Returns the arriving
        ``Permanent`` for a battlefield destination and None otherwise; None
        also means the card was not in exile to move, which is CR 608.2b doing
        as much as possible rather than creating a card from nowhere.

        A hand or a library goes through ``put_card_into_hand`` /
        ``put_card_into_library`` rather than appending, because CR 903.9b has
        no single fire site and this is one more of the places that would have
        forgotten it.
        """
        owner = self.players[int(entry["owner_index"])]
        card = entry["card"]
        if card not in owner.exile:
            return None
        owner.exile.remove(card)
        if zone == "hand":
            self.put_card_into_hand(owner, card)
            return None
        if zone == "library":
            self.put_card_into_library(owner, card)
            return None
        if zone != "battlefield":
            getattr(owner, zone).append(card)
            return None
        arrival = Permanent(card=card)
        self._put_permanent_onto_battlefield(int(entry["owner_index"]), arrival, None)
        if entry.get("tapped"):
            arrival.tapped = True
        if entry.get("counters"):
            from ..handlers.zones import restore_noted_counters

            restore_noted_counters(self, arrival, entry["counters"])
        return arrival

    def return_linked_exile(self, permanent: Permanent, why: str, ending: str) -> None:
        """Give back everything *ending* gives back of what was exiled with
        ``permanent`` (CR 400.7, 610.3).

        Two callers, because two things can end a linked exile: the permanent
        leaving the battlefield (Kitesail Freebooter, Idol of Endurance) and —
        Tawnos's Coffin alone — the permanent becoming untapped. One function
        because the unwinding is identical and the difference is only what says
        the word.

        *ending* is which of the two happened, and it is matched against the
        entry's own ``ends_on`` rather than assumed: only a card exiled by an
        ability that printed "or becomes untapped" comes back for an untap.
        Without that test the untap caller ended every linked exile in the
        game, and Idol of Endurance — which taps for its own ability — dumped
        its whole pile into the graveyard at the next untap step.
        """
        from ..linked_exile import take_linked_entries

        entries = take_linked_entries(permanent, ending=ending)
        returned: Permanent | None = None
        for entry in entries:
            owner = self.players[int(entry["owner_index"])]
            card = entry["card"]
            # Back to the zone it was taken from. Kitesail Freebooter takes from
            # a hand, Idol of Endurance from a graveyard and Tawnos's Coffin
            # from the battlefield, and a card returned to the wrong one is a
            # card the effect created out of nothing — so the origin rides the
            # entry rather than being a constant here.
            destination = str(entry.get("to", "hand"))
            if card not in owner.exile:
                continue
            arrival = self.leave_linked_exile(entry, destination)
            if arrival is None:
                self.log.append(
                    f"{card.name} returns to {owner.name}'s {destination} "
                    f"({permanent.card.name} {why})"
                )
                continue
            # "…**attached to that permanent**" — the Auras go back onto the
            # creature the entry before them brought back, which is why they
            # travel in one record and in printed order. Nothing to attach to
            # means the Aura simply arrives, and CR 704.5n's sweep bins it.
            if entry.get("attach_to_returned") and returned is not None:
                from ..auras import attach_aura

                attach_aura(arrival, returned)
            else:
                returned = arrival
            self.log.append(
                f"{card.name} returns to the battlefield "
                f"({permanent.card.name} {why})"
            )
        if entries:
            self._recompute_continuous_effects()

    @staticmethod
    def default_sacrifice_pick(candidates: list[Permanent]) -> Permanent:
        """Which of *candidates* a seat that did not choose gives up.

        Every sacrifice a player owes has an interactive answer and a
        deterministic one, and the deterministic one has to be the *same* rule
        wherever it is reached — an AI paying an activation cost, a headless
        script casting a spell, and the forced-sacrifice prompt's default were
        three copies of "keep the one whose death loses the game for last, then
        take the smallest", which is exactly the kind of near-duplicate that
        drifts into three different answers.

        ``permanent_id`` breaks the tie, so the pick is stable across a run and
        the AI simulation stays seed-reproducible.
        """
        return min(candidates, key=GameHelpersMixin.sacrifice_preference_key)

    @staticmethod
    def sacrifice_preference_key(permanent: Permanent):
        """The order a seat gives permanents up in — lowest first.

        Split out of :meth:`default_sacrifice_pick` because a caller that has to
        pay **several** costs at once cannot pick them one at a time: CR 508.1g's
        sacrifices are one payment, and which permanent answers which cost is a
        matching (`_declaration_sacrifice_plan`). That planner needs the policy
        as an *order* rather than as a winner, and a second ordering written
        beside this one is exactly the drift the method above exists to stop.
        """
        return (
            "you lose the game" in permanent.effective_card.oracle_text.lower(),
            permanent.effective_power,
            permanent.permanent_id,
        )

    def sacrifice_permanent(self, permanent: Permanent) -> Permanent | None:
        """Sacrifice *permanent* — CR 701.21a, the one transition.

        "To sacrifice a permanent, its controller moves it from the battlefield
        directly to its owner's graveyard." Two halves, and the second one is
        where this was going wrong: of the thirteen sacrifice sites, **seven**
        reached the graveyard by appending the card to some player's list
        instead of going through :meth:`_permanent_to_graveyard` — so a
        sacrificed permanent skipped everything that transition does. The owner
        lookup (CR 400.3, which is a different player from the controller for
        anything stolen), token cessation (CR 704.5d), the would-die
        replacements (CR 614), the Aura teardown, and the death count.

        The death count is the one with a card behind it in the shipped pool.
        CR 700.4 defines *dies* as "is put into a graveyard from the
        battlefield", and a sacrifice is exactly that — so a creature sacrificed
        to cast Sacrifice has died, and Scavenging Ghoul's "for each creature
        that died this turn" must count it. It did not: the cost path appended
        the card and left ``creatures_died_this_turn`` at zero.

        Sacrificing is **not** destroying, so regeneration and the effects that
        replace destruction can't apply (701.21a again). That holds here by
        shape rather than by a flag — regeneration is offered by the destruction
        sweeps, and this doesn't go through them.

        Returns the permanent when it was on the battlefield to sacrifice, None
        when it was not. **The log line stays with the caller**: "…to activate
        Ashnod's Altar", "…on upkeep", "…(Lord of the Pit)" is that site's
        prose, not this rule's.
        """
        seat = self.controller_index_of(permanent)
        if seat is None:
            return None
        # Resolved before the removal, because afterwards there is no
        # battlefield to read it off.
        controller = self.players[seat]
        if self.remove_from_battlefield(permanent) is None:
            return None
        # "…**if it wasn't sacrificed**, you may pay {3}." (Urza's Miter.) How a
        # permanent left is not derivable from where it ended up — a sacrifice
        # and a destruction both put it in the same graveyard — so the one
        # sacrifice transition records it, and the death dispatcher reads it
        # back as last-known information (CR 608.2h). Set before the graveyard
        # move, because that is what announces the death.
        permanent.metadata["was_sacrificed"] = True
        self._permanent_to_graveyard(controller, permanent)
        # Announced after the permanent has gone, so a trigger that reads the
        # board sees the board the sacrifice left behind (CR 603.10 — the
        # trigger looks back at a game state that already happened).
        emit(self, "you_sacrifice_permanent", subject=permanent, seat=seat)
        return permanent

    # ------------------------------------------------------------------
    # Combat's slots, kept honest across a removal
    # ------------------------------------------------------------------

    def _combat_seat_of_blocker(self, attacker_index: int) -> int | None:
        """Which seat a blocker index belongs to, given the attacker it blocks.

        ``combat_banding_damage`` and ``combat_multiblock_damage`` record blocker
        slots with no seat beside them, which is unambiguous in a duel and not
        in a CR 802 multi-defender combat. The seat is recoverable: a blocker
        blocks an attacker, and ``combat_attackers`` says which player that
        attacker is attacking. Read before any map is rewritten, so it answers
        from the pre-removal numbering.
        """
        seat = self.combat_attackers.get(attacker_index)
        if seat is None:
            return self.combat_defending_player_index
        return seat

    def _renumber_combat_after_removal(self, vacated: dict[int, list[int]]) -> None:
        """Keep every combat map pointing at the creatures it meant.

        Combat is recorded as **battlefield slots** — attacker index, blocker
        index — and a slot is not a name. A creature dying in the first-strike
        damage step shifts every later slot on its controller's battlefield down
        by one, so an attacker recorded as index 3 silently becomes whatever
        index 3 is now. That was the bug this whole thread of work was chasing,
        and consolidating removal into one transition is what made it fixable in
        one place instead of 41.

        Two things happen to a recorded slot. If its own creature left, the
        entry is **dropped** — a dead attacker is not attacking. Otherwise it is
        **shifted** down by the number of departing creatures that sat ahead of
        it on the same battlefield.

        The seat for each index is not guessed: an attacker index is always the
        active player's (``declare_attackers`` refuses any other controller), a
        blocker index in ``combat_blockers`` comes from its own outer key, and
        the two damage-assignment maps recover it through
        :meth:`_combat_seat_of_blocker`.
        """
        if not vacated:
            return

        def shift(seat: int | None, index: int) -> int | None:
            """*index* after the removal, or None if that creature is the one gone."""
            gone = vacated.get(seat) if seat is not None else None
            if not gone:
                return index
            if index in gone:
                return None
            return index - sum(1 for slot in gone if slot < index)

        attacker_seat = self.active_player_index
        # Snapshot the attacker->defender map before anything is rewritten; the
        # blocker-seat lookups below read it.
        blocker_seat_of = {
            attacker: self._combat_seat_of_blocker(attacker)
            for attacker in list(self.combat_attackers)
        }

        def shift_attacker(index: int) -> int | None:
            return shift(attacker_seat, index)

        self.combat_attackers = {
            moved: defender
            for attacker, defender in self.combat_attackers.items()
            if (moved := shift_attacker(attacker)) is not None
        }

        # Keys are attacker slots on the active seat, exactly like
        # combat_attackers; the values are permanent ids and never renumber.
        self.combat_attacked_planeswalkers = {
            moved: walker_id
            for attacker, walker_id in self.combat_attacked_planeswalkers.items()
            if (moved := shift_attacker(attacker)) is not None
        }

        rebuilt_blockers: dict[int, dict[int, list[int]]] = {}
        for defender_seat, blocks in self.combat_blockers.items():
            rebuilt: dict[int, list[int]] = {}
            for blocker, attackers in blocks.items():
                moved_blocker = shift(defender_seat, blocker)
                if moved_blocker is None:
                    continue
                moved_attackers = [
                    moved
                    for attacker in attackers
                    if (moved := shift_attacker(attacker)) is not None
                ]
                # A blocker whose every attacker has gone is no longer blocking
                # anything; dropping it keeps "is this creature blocking?" true.
                if moved_attackers:
                    rebuilt[moved_blocker] = moved_attackers
            if rebuilt:
                rebuilt_blockers[defender_seat] = rebuilt
        self.combat_blockers = rebuilt_blockers

        self.combat_bands = [
            moved_band
            for band in self.combat_bands
            if (moved_band := [
                moved for member in band if (moved := shift_attacker(member)) is not None
            ])
        ]

        self.combat_band_blocks = {
            moved_attacker: moved_blockers
            for attacker, blockers in self.combat_band_blocks.items()
            if (moved_attacker := shift_attacker(attacker)) is not None
            and (moved_blockers := [
                moved
                for blocker in blockers
                if (moved := shift(blocker_seat_of.get(attacker), blocker)) is not None
            ])
        }

        self.combat_banding_damage = {
            moved_attacker: moved_assignment
            for attacker, assignment in self.combat_banding_damage.items()
            if (moved_attacker := shift_attacker(attacker)) is not None
            and (moved_assignment := {
                moved: amount
                for blocker, amount in assignment.items()
                if (moved := shift(blocker_seat_of.get(attacker), blocker)) is not None
            })
        }

        rebuilt_multiblock: dict[int, dict[int, int]] = {}
        for blocker, assignment in self.combat_multiblock_damage.items():
            # This map keys by blocker, so its seat comes from an attacker the
            # blocker is blocking rather than from the key itself.
            seat = next(
                (blocker_seat_of.get(attacker) for attacker in assignment),
                self.combat_defending_player_index,
            )
            moved_blocker = shift(seat, blocker)
            if moved_blocker is None:
                continue
            moved_assignment = {
                moved: amount
                for attacker, amount in assignment.items()
                if (moved := shift_attacker(attacker)) is not None
            }
            if moved_assignment:
                rebuilt_multiblock[moved_blocker] = moved_assignment
        self.combat_multiblock_damage = rebuilt_multiblock

        self.combat_attacker_piles = {
            moved: side
            for attacker, side in self.combat_attacker_piles.items()
            if (moved := shift_attacker(attacker)) is not None
        }
        self.combat_defender_piles = {
            moved: side
            for creature, side in self.combat_defender_piles.items()
            if (moved := shift(self.combat_left_right_defender_index, creature)) is not None
        }

    def permanent_ids_at(self, seat, index):
        """The stable id(s) of whatever sits at *index* on *seat*'s battlefield.

        Takes the index shape the wire and the stack already speak — an int, a
        list of ints, or None — and returns the same shape in ids, so a caller
        recording a target keeps the two readable side by side. An entry that
        does not resolve becomes None rather than being dropped, because a
        multi-target list is positional and a shorter list would silently
        re-pair the surviving targets with the wrong slots."""
        if isinstance(index, list):
            return [self.permanent_ids_at(seat, entry) for entry in index]
        permanent = self.permanent_at(seat, index)
        return None if permanent is None else permanent.permanent_id

    def _stack_push(self, item=None, *, targets_already_chosen: bool = False):
        """Put *item* on the stack and finish announcing it, then return it.

        Two steps, because the second is only meaningful once the first has
        happened: :meth:`_stack_push_object` records the targets' identities
        and appends the object, and then a **modal triggered ability** chooses
        its mode and that mode's targets, which CR 700.2b and CR 603.3c place
        exactly here — "as part of putting that ability on the stack".

        It hangs off this method rather than off ``_enqueue_triggered_ability``
        for the reason this method exists at all: it is *the* one place an
        object goes on the stack, and the enqueue helper is not — the attack
        and block trigger fire sites in ``phases/declare_attackers_step.py``
        build their own ``StackItem`` and push it here directly. A choice armed
        one layer up covered the enqueued triggers and quietly missed those,
        which is the fire-site problem in miniature.
        """
        self._stack_push_object(item)
        self._choose_trigger_mode(item)
        # …and its non-modal twin: an ability whose printed noun phrase is a
        # *choice* the event did not make chooses it now, at the same moment
        # and for the same rule (CR 603.3d/601.2c). Both hang off this method
        # for the reason above — it is the one place an object goes on the
        # stack, and a fire site that builds its own StackItem still passes
        # through here.
        #
        # *targets_already_chosen* is the one exception, and it is a rule
        # rather than a list of callers: an **activated** ability chose its
        # targets when it was activated (CR 602.2b, gated once in
        # `legality.activation_target_refusal`), and a **copy** inherits the
        # original's (CR 707.10). Both were announced with their targets
        # already made, so asking again would replace a choice a player has
        # made with one they have not.
        if not targets_already_chosen:
            self._choose_trigger_targets(item)
        return item

    def _stack_push_object(self, item) -> None:
        """Put *item* on the stack, recording its target's identity (CR 601.2c).

        The one place an object goes on the stack, and the reason it is one
        place: a stack object is the engine's only structure that outlives the
        moment it was built. Everything else that holds a battlefield index
        uses it within the same step, where the list cannot renumber
        underneath it; a spell waits for priority to pass, for responses to be
        cast, and for everything above it to resolve — and any of those can
        take a permanent off the battlefield and shift every later slot down.

        So the index the caller chose is stamped into an id *here*, at the
        boundary, while it is still known to mean what it said. Resolution
        reads the id (``engine/handlers/_common.py``) and only falls back to
        the index when the id no longer resolves, which is exactly the
        situation the old code was already in.

        **A graveyard target is stamped here too, and first.** Its index is a
        slot in a different list, so the battlefield stamping below answers a
        question the item never asked: Raise Dead naming graveyard slot 1 was
        handed the id of whatever permanent sat in battlefield slot 1."""
        # Each chosen mode of a multi-mode spell names its own object, so each
        # one is stamped here for the same reason the item's own target is: the
        # index was chosen while it still meant what it said, and this is the
        # boundary it stops being safe to hold one across (CR 400.7).
        for mode in item.chosen_modes:
            if mode.target_permanent_index is None or mode.target_permanent_id is not None:
                continue
            seat = mode.target_player_index
            if seat is None:
                seat = (
                    1 - item.caster_index if len(self.players) == 2
                    else item.caster_index
                )
            if 0 <= seat < len(self.players):
                mode.target_permanent_id = self.permanent_ids_at(
                    seat, mode.target_permanent_index
                )
        spec = graveyard_target_spec(
            item.card,
            compile_card_oracle(item.card),
            mode_index=item.chosen_mode_index,
            instruction=item.ability_instruction,
        )
        if spec is not None:
            item.target_graveyard_card = self.stamp_graveyard_targets(
                self.graveyard_target_seat(item, spec), item.target_permanent_index
            )
            self.stack.append(item)
            return
        if item.target_permanent_id is not None:
            # The caller already knows the identities. The web layer does: it
            # resolves `target_permanent_ids` off the wire and then used to
            # throw them away here, so a pair of targets on *two* battlefields
            # was re-derived against the single `target_player_index` and the
            # second slot resolved to whatever sat at that index on the wrong
            # board. Garruk, Savage Herald's -2 names one creature you control
            # and then anyone's, so it is the shape that needed this.
            self.stack.append(item)
            return
        seat = item.target_player_index
        if seat is None:
            # The convention resolution uses when no target player was named.
            seat = 1 - item.caster_index if len(self.players) == 2 else item.caster_index
        if 0 <= seat < len(self.players):
            item.target_permanent_id = self.permanent_ids_at(seat, item.target_permanent_index)
        self.stack.append(item)
        self._announce_targeting(item)

    def _announce_targeting(self, item) -> None:
        """"…becomes the target of a spell or ability" (CR 603.2, Warden of the
        Woods).

        Announced here because here is where the targets exist: CR 601.2c has a
        spell choose them as it is cast and CR 602.2b an ability as it is
        activated, which is exactly the moment an object is put on the stack.
        Reading the ids the stamping above just settled means a target that has
        already changed hands or left is not announced against a stale slot.

        One event per targeted permanent, and the announcement carries *who* did
        the targeting — the narrowing "an opponent controls" is about the spell's
        controller, which nothing downstream could recover from the permanent.
        """
        from ..events import emit

        ids = item.target_permanent_id
        if ids is None:
            return
        for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids]):
            if not isinstance(permanent_id, int):
                continue
            targeted = self.permanent_by_id(permanent_id)
            if targeted is None:
                continue
            emit(
                self, "self_becomes_target",
                subject=targeted,
                source_seat=item.caster_index,
            )

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
        """Destroy every permanent on *player*'s battlefield that ``matches``.

        Indestructible permanents survive (when respected); a creature's
        regeneration shield is consumed instead of destruction (when allowed).
        Each destruction routes through ``_permanent_to_graveyard`` while the
        permanent is still listed, matching the sweep loops this consolidates.
        Returns the destroyed permanents.

        The survivors list this used to build and assign is gone: it says what
        stays, when the interesting set is what leaves, and it was one of the
        41 open-coded battlefield rebuilds. Collecting the departing and handing
        them to :meth:`remove_all_from_battlefield` is the same operation said
        the other way round, through the one transition.
        """
        destroyed: list[Permanent] = []
        for permanent in list(self.controlled_by(player)):
            if not matches(permanent):
                continue
            # Pyramids: a shielded land survives its next destruction this turn.
            if self._consume_land_destruction_shield(permanent):
                continue
            if respect_indestructible and self._is_indestructible(permanent):
                continue
            # The same one decision the other destruction path asks
            # (`engine/regeneration.py`): shield, static form and the "can't be
            # regenerated" rider together. It clears the marked damage CR
            # 701.19a-b require, which this copy did not — a creature the
            # lethal-damage sweep regenerated kept its damage and survived only
            # because the caller happened to pass an ``on_regenerate`` that
            # cleared it, so a sweeper without one re-destroyed it on the next
            # pass.
            if (
                allow_regeneration
                and permanent.is_creature
                and regeneration_replaces_destruction(self, permanent)
            ):
                if on_regenerate is not None:
                    on_regenerate(permanent)
                continue
            self._permanent_to_graveyard(player, permanent)
            if on_destroy is not None:
                on_destroy(permanent)
            destroyed.append(permanent)
        self.remove_all_from_battlefield(destroyed)
        return destroyed

    def _fire_permanent_dies_triggers(self, dead_permanent: Permanent) -> None:
        """"Whenever <noun phrase> is put into a graveyard from the
        battlefield" — any permanent type, narrowed by the printed phrase
        (Tablet of Epityr, Urza's Miter).

        Fired from ``_permanent_to_graveyard``, which is the one seam every
        path to a graveyard already goes through, rather than from the several
        places a permanent can die. A creature death additionally fires
        ``_fire_creature_dies_triggers``: that condition is a different kind
        with its own last-known-information context, and a creature is a
        permanent, so both are announced and each observer's own condition
        decides which it answers to.

        The narrowing is asked of ``subject_matches`` with the *observer's*
        seat, which is what makes "an artifact **you control**" mean the
        controller of the triggered ability (CR 109.5) rather than the
        controller of the dying permanent.
        """
        from ..subject_filters import subject_matches

        events: list[dict] = []
        for controller_index, observer in self.permanents_with_controller():
            for trig in matching_triggers(
                observer.effective_card, condition_kinds={"permanent_dies"},
            ):
                if trig.instruction is None:
                    continue
                if not subject_matches(
                    self,
                    dead_permanent,
                    trig.condition.payload.get("dying_filter"),
                    observer=controller_index,
                    source=observer,
                ):
                    continue
                # "…is put into **your** graveyard from the battlefield"
                # (Enduring Renewal). Which graveyard it landed in, which
                # CR 404.1 makes a question about the card's **owner** and not
                # about who controlled the permanent — so it is asked here
                # rather than folded into the filter above, where
                # `subject_matches` has no owner to read.
                if trig.condition.payload.get("dying_graveyard_owner") == "your":
                    owner_index = self.owner_index_of(dead_permanent)
                    if owner_index != controller_index:
                        continue
                # "…if it wasn't sacrificed" (Urza's Miter). CR 603.4's
                # intervening-if, checked when the trigger would fire — and the
                # only thing that can answer it is the record the sacrifice
                # transition left, since the graveyard looks the same either
                # way.
                if (
                    trig.condition.payload.get("dying_not_sacrificed")
                    and dead_permanent.metadata.get("was_sacrificed")
                ):
                    continue
                events.append(make_trigger_event(
                    controller_index, observer, trig,
                    trigger_context={
                        "dead_name": dead_permanent.card.name,
                        # The card itself, for "return **it** to your hand"
                        # (Enduring Renewal). The name cannot answer: a
                        # graveyard is a list of `CardDefinition` and two copies
                        # of a card are the same immutable object, so a name
                        # match finds whichever entry came first. The same key
                        # the creature-death context has carried since Puppet
                        # Master, recorded here because this fire site is where
                        # a non-creature permanent's death is announced.
                        "dead_card": dead_permanent.card,
                    },
                ))
        self._enqueue_triggered_batch(events)

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
        # Last-known information about the creature that died (CR 603.10),
        # frozen here because nothing downstream can read it: by the time a
        # trigger resolves the permanent is in a graveyard with no counters.
        dead_seat = self.controller_index_of(dead_permanent)
        died_context = {
            "dead_name": dead_permanent.card.name,
            # The card itself, for "return **that card** to its owner's hand"
            # (Puppet Master). The *name* above cannot answer: a graveyard is a
            # list of `CardDefinition`, two copies of a card are the same
            # immutable object, and a name match would find whichever entry came
            # first. The identity is what locates the one that just died.
            "dead_card": dead_permanent.card,
            "had_plus1_counter": int(dead_permanent.metadata.get("plus_counters", 0)) > 0,
            # Who controlled it, for "that player loses 2 life" (Massacre
            # Wurm): the graveyard card cannot say, and under Control Magic
            # the controller is not the owner. One key across every event that
            # is about an object — the blocker's controller Gloom Sower reads
            # is the same question asked of a different event.
            "event_subject_controller": dead_seat,
        }
        for controller_index, observer in self.permanents_with_controller():
            program = compile_card_oracle(observer.card)
            # The two controller-scoped death conditions, which differ only in
            # *whose* creature died — so the scope is the whole dispatch and
            # they cannot share a kind. Collected before the self-exclusion
            # below, because "this creature or another creature you control"
            # (Basri's Lieutenant) counts the source's own death.
            scoped = (
                "creature_you_control_dies" if dead_seat == controller_index
                else "creature_opponent_controls_dies"
            )
            if dead_seat is not None:
                for trig in matching_triggers(
                    observer.effective_card, condition_kinds={scoped},
                ):
                    events.append(make_trigger_event(
                        controller_index, observer, trig,
                        trigger_context=dict(died_context),
                    ))
            # "Whenever equipped creature dies, put a soul counter on this
            # Equipment." (Malefic Scythe.) The observer is what the dead
            # creature was carrying, so the scope is an attachment rather than a
            # seat — asked here because this is the one place a creature's death
            # is announced, and a second fire site is a second place to forget.
            # The direction matters: the observer is attached *to* the dead
            # creature, not the other way round. Both spellings of "attached"
            # are asked because both exist — the list an Aura joins, and the
            # single slot an Equipment sets.
            if observer in auras_attached_to(dead_permanent) or (
                observer.metadata.get("attached_to") is dead_permanent
            ):
                for trig in matching_triggers(
                    observer.effective_card,
                    condition_kinds={"attached_creature_dies"},
                ):
                    events.append(make_trigger_event(
                        controller_index, observer, trig,
                        trigger_context=dict(died_context),
                    ))
            if observer is dead_permanent:
                continue
            for trig in program.triggered_abilities:
                # Sengir Vampire: "Whenever a creature dealt damage by this
                # creature this turn dies, put a +1/+1 counter on this creature."
                # Axelrod Gunnarson prints the same condition with a different
                # effect, and this branch used to require the counter
                # instruction as well — a dispatcher narrowed to the one card
                # that reached it first, so a second card carrying the condition
                # compiled a real instruction and fired nowhere. What the
                # ability *does* is the effect's business; the condition is
                # about a death.
                if (
                    trig.condition.kind == "creature_dealt_damage_by_self_dies"
                    and trig.instruction is not None
                ):
                    damagers = dead_permanent.metadata.get("damaged_by_sources_this_turn", [])
                    # By identity: ``in`` compares Permanent by value, and a
                    # look-alike of the killer is not the killer (CR 400.7).
                    if any(entry is observer for entry in damagers):
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
                    obs_text = observer.effective_card.oracle_text.lower()
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
        *,
        was_cast: bool = False,
        from_zone: str | None = None,
    ) -> None:
        """Put *permanent* onto the battlefield — the one entry path there is.

        *was_cast* is CR 701.5a's distinction and defaults to the common case:
        of the entry sites in the engine, exactly one is a resolving permanent
        spell, and every other — a token, a reanimation, a cleanup return, an
        effect that puts a card into play — is a permanent that was **not**
        cast. Containment Priest is the first card to ask, and the honest answer
        for a caller that has not thought about it is the one that describes
        what most callers do.

        The default is also the direction that fails *visibly*: a cast creature
        wrongly exiled is a card a player watches disappear, where a reanimation
        wrongly surviving is nothing happening.
        """
        # CR 614: "if a nontoken creature would enter … exile it instead"
        # (Containment Priest). Asked before anything else, because a
        # replacement means the permanent never enters at all — no id is
        # stamped, no layer contribution is made, no enters-the-battlefield
        # trigger is announced. A "when it enters, exile it" reading would let
        # every one of those happen first, which is a different card.
        consumed, _ = apply_replacements(
            self,
            "would_enter_battlefield",
            {
                "permanent": permanent,
                "controller_index": controller_index,
                "was_cast": was_cast,
                # CR 616.1 asks the *affected* player to choose among contending
                # effects; for an entry that is the seat the permanent would
                # enter under.
                "player": self.players[controller_index],
            },
        )
        if consumed:
            return
        # "…if it **entered from your graveyard**" (Archfiend's Vessel). Stamped
        # on the permanent rather than kept on the game, because the question is
        # asked of one object and a permanent that leaves takes the answer with
        # it (CR 400.7 gives the next one a new identity and a fresh stamp).
        # None means the caller did not say, which reads as "not from anywhere
        # this asks about" — the same defaulting as ``was_cast``, and the same
        # reason: most entries are not from a zone any card asks about.
        if from_zone is not None:
            permanent.metadata["entered_from_zone"] = from_zone
        # CR 400.7: what enters is a *new object*, so it gets a new identity —
        # nothing that held the old id may address it. Stamped before the append
        # so no reader can observe the permanent on the battlefield under an id
        # it is about to lose.
        permanent.permanent_id = next_permanent_id()
        self.players[controller_index].battlefield.append(permanent)
        # "…put a nontoken permanent onto the battlefield" (Arboria, CR 506.3):
        # the per-turn half of the last-own-turn record, folded per seat at the
        # turn boundary (mixins/turn_management.begin_turn_bookkeeping). Here
        # because this is the one entry path there is — a fire site per caller
        # is the pattern that forgot `become_tapped` 41 times.
        if not permanent.metadata.get("is_token"):
            self.nontoken_permanents_entered_this_turn[controller_index] = (
                self.nontoken_permanents_entered_this_turn.get(controller_index, 0) + 1
            )
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
        # The "…**then** X" half of an entry replacement (Land Equilibrium's
        # "puts that land onto the battlefield then sacrifices a land"). After
        # the append and after the recompute, because "then" means the new
        # permanent is on the battlefield and is itself a legal choice.
        apply_entry_riders(self, permanent, controller_index)
        # "Whenever a creature you control with power 4 or greater enters"
        # (Garruk's Uprising). Every entry path in the engine — a resolving
        # spell, a token, a reanimation, a cleanup return — comes through this
        # one function, so the announcement is one emit rather than a fire site
        # per path. After the recompute on purpose: a filter about power or type
        # asks what the board makes the permanent, and a lord that applied as it
        # entered is part of that (CR 611.3a).
        emit(
            self, "matching_permanent_enters", subject=permanent,
            # "…deals damage equal to **that creature's** power" (Terror of the
            # Peaks). Frozen here rather than read at resolution: the trigger
            # resolves after the entry, and by then the creature may have been
            # pumped, shrunk or destroyed — CR 608.2's number is the one the
            # event had. Recorded on every entry because the cost is one integer
            # and the alternative is a fire site that knows which cards care.
            entering_power=max(0, permanent.effective_power),
        )
        # **And the permanent's own "when this enters" trigger**, for every entry
        # that is not a cast.
        #
        # That trigger was fired from exactly one place — the resolution of a
        # permanent *spell* — so a permanent put onto the battlefield any other
        # way never fired it at all. A reanimated Archfiend's Vessel made no
        # Demon; a Niambi put into play returned nothing. Both reported
        # supported, because the ability compiles perfectly and nothing ran it.
        #
        # The cast path keeps its own call rather than deferring to this one:
        # it has the caster's cast-time target choice to thread through
        # (CR 601.2c), which an entry from a graveyard or a token creation has
        # no equivalent of. ``was_cast`` is what keeps the two from both firing,
        # and it is the same flag CR 701.5a needed for Containment Priest — one
        # fact about an entry, asked by two rules.
        if not was_cast:
            self._apply_self_enters_battlefield_triggers(
                controller_index, permanent, target_player_index, None, None,
            )
