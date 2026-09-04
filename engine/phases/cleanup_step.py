from __future__ import annotations

"""Cleanup step (CR 514).

The active player discards down to maximum hand size, then all damage is removed
and "until end of turn" effects end (CR 514.2): regeneration shields, temporary
P/T buffs, damage prevention pools, and the EOT metadata flags. Creatures exiled
"until end of turn" return here (CR 610.3). No player normally receives priority.
"""

from ..delayed_triggers import expire_delayed_triggers, fire_delayed_triggers
from ..cast_permissions import expire_end_of_turn as expire_end_of_turn_permissions
from ..cast_timing import CAST_AT_INSTANT_SPEED
from ..hand_size import maximum_hand_size
from ..models import Permanent
from ..keywords import (clear_granted_ability_lines,
                        clear_granted_keywords,
                        clear_removed_ability_keywords)
from ..control import end_until_eot_control_changes
from ..handlers.board_misc import LAND_TYPE_UNTIL_EOT
from ..handlers.control_changes import TAP_WHEN_CONTROL_LOST
from ..land_types import end_land_type_changes_from
from ..layer_bridge import GAINED_TYPES
from ..mixins._constants import _EOT_METADATA_KEYS
from ..damage_redirects import clear_redirects
from ..land_mana_swaps import clear_swaps as clear_land_mana_swaps
from ..shields import clear_shields
from ..pt import remove_temporary_pt


class CleanupStepMixin:
    def resolve_cleanup_step(
        self,
        player_index: int,
        discard_hand_indices: list[int] | None = None,
        defer_discard_selection: bool = False,
    ) -> bool:
        phase = "ending"
        step = "cleanup"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)

        # CR 514.2: "until end of turn" effects end. A global static whose
        # source has left the battlefield but whose effect continued (Titania's
        # Song) stops here — dropping it from the list is the whole removal,
        # because the effect was only ever derived from that list.
        if self.lingering_global_statics:
            self.lingering_global_statics.clear()
            self._refresh_dynamic_creatures()

        # "…the controller of the permanent it becomes sacrifices it at the
        # beginning of the next cleanup step" (Mirage's five flash Auras).
        # CR 514.1's moment, and the *first* thing this step does, because the
        # sentence says "at the beginning of". A sweep over the mark rather than
        # a delayed trigger armed at the cast, for the reason every other sweep
        # in this engine exists: the mark can arrive by more than one route (an
        # Aura that becomes a permanent, and any later card that copies the
        # sentence), and a rule with several fire sites is a rule that gets
        # forgotten at one of them.
        self._sacrifice_permanents_cast_at_instant_speed()

        active_player = self.players[player_index]
        cleanup_completed = True
        control_reverted = False
        # CR 402.2's seven, and the two printed lines that change it — asked of
        # `engine/hand_size.py`, which is also what the support gate and the
        # parse-coverage report ask. It was a literal here, so Cursed Rack's
        # "the chosen player's maximum hand size is four" compiled, reported
        # supported, and never took a card off anyone.
        max_hand_size = maximum_hand_size(self, player_index)
        if max_hand_size is not None:
            excess = max(0, len(active_player.hand) - max_hand_size)
            if excess:
                if discard_hand_indices is not None:
                    unique_indices = sorted(set(discard_hand_indices))
                    if len(unique_indices) != excess:
                        raise ValueError(f"expected {excess} cleanup discards, got {len(unique_indices)}")
                    if any(index < 0 or index >= len(active_player.hand) for index in unique_indices):
                        raise ValueError("cleanup discard index out of range")
                    for hand_index in sorted(unique_indices, reverse=True):
                        discarded = active_player.hand.pop(hand_index)
                        self._discard_card(active_player, discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")
                elif defer_discard_selection:
                    cleanup_completed = False
                else:
                    for _ in range(excess):
                        discarded = active_player.hand.pop(0)
                        self._discard_card(active_player, discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")

        self.combat_damage_prevented_until_eot = False
        # "…this turn" (Blind Fury). Cleared here and **not** at the end of
        # combat, unlike the Fog flag above: the sentence names the turn, so a
        # second combat phase is still doubled.
        self.combat_damage_doubled_between_creatures.clear()
        self.combat_damage_prevented_for = []
        self.combat_damage_prevented_except_from = []
        # CR 603.7b: a delayed trigger scoped to "this turn" that has not fired
        # (or has fired all it will) expires with the turn. Which entries those
        # are is the entry's own ``duration``, read by one sweep in
        # ``engine/delayed_triggers.py``.
        expire_delayed_triggers(self)
        # CR 611.2a: "until end of turn" / "this turn" cast-or-play permissions
        # end with the turn; an undurationed grant (Chandra, Flame's Catalyst's
        # −2) survives the sweep and dies with its card's zone instead.
        expire_end_of_turn_permissions(self)
        # "…can't block this turn" blanket restrictions end with the turn too.
        self.blocking_restrictions_until_eot.clear()
        # "Creatures can't attack this turn." (Festival.) CR 514.2 ends it with
        # the same cleanup, beside its blocking twin rather than anywhere else,
        # so the two cannot come to disagree about when "this turn" is over.
        self.attack_restrictions_until_eot.clear()
        # "Until the end of your next turn, they can't phase in." (Teferi,
        # Timeless Voyager.) The block counts the *caster's* turn ends; this
        # cleanup ends the active player's turn, so their countdowns tick.
        for player in self.players:
            for perm in player.phased_out:
                block = perm.metadata.get("phase_in_blocked")
                if (
                    isinstance(block, dict)
                    and block.get("seat") == self.active_player_index
                    and int(block.get("turn_ends_remaining", 0)) > 0
                ):
                    block["turn_ends_remaining"] = int(block["turn_ends_remaining"]) - 1
        for player in self.players:
            # CR 615.3: every prevention shield lasts until it is used up or its
            # duration expires, and "until end of turn" expires here. One sweep
            # over the collection rather than a line per card-named field —
            # which is also why a new kind of shield needs no line here.
            clear_shields(player)
            # CR 614.9's redirects expire with the turn for the same reason and
            # by the same one sweep (engine/damage_redirects.py).
            clear_redirects(player)
            # "Until end of turn, if you tap a land you control for mana, it
            # produces {U} instead of any other type." (Deep Water.) A CR 611.2
            # swap with a printed window, and it expires by the same one sweep
            # for the same reason (engine/land_mana_swaps.py).
            clear_land_mana_swaps(player)
            player.mirror_damage_charges = 0
            player.mirror_damage_sources = []
            player.channel_active_until_eot = False
            # "For one spell **this turn**" (North Star): an unused permission
            # expires with the turn, the same way an unused regeneration shield
            # below does.
            player.spend_mana_as_though_grants = []
            player.prevent_one_damage_emblems = []
            for permanent in self.controlled_by(player):
                permanent.damage_marked = 0
                clear_shields(permanent)
                clear_redirects(permanent)
                # 614.8 / 701.19a: an unused regeneration shield lasts only until
                # the end of the turn it was created.
                permanent.regeneration_shield = 0
                remove_temporary_pt(permanent, "end_of_turn")
                # "Target land becomes the basic land type of your choice
                # **until end of turn**." (Jinx.) The untap step's twin, one
                # turn boundary earlier: the record is keyed by a label rather
                # than by the permanent that made it — Jinx is an instant and
                # has none — and it is dropped here by that label's prefix.
                # Dropping one contribution *is* the reversion (CR 611.3b):
                # what the land is afterwards is whatever the other
                # contributions still say, not what was printed on it.
                end_land_type_changes_from(permanent, prefix=LAND_TYPE_UNTIL_EOT)
                for key in _EOT_METADATA_KEYS:
                    permanent.metadata.pop(key, None)
                # A gained type whose duration is "until end of turn" ends here,
                # and ends by the record leaving — the permanent's own type line
                # was never touched, so there is nothing to restore. Records
                # with another duration are left alone: a permanent one
                # (Ashnod's Transmogrant) outlives every turn boundary there is,
                # which is why this cannot be a plain key in the sweep above.
                gained = permanent.metadata.get(GAINED_TYPES)
                if gained:
                    kept = [g for g in gained if g.get("duration") != "until_end_of_turn"]
                    if kept:
                        permanent.metadata[GAINED_TYPES] = kept
                    else:
                        permanent.metadata.pop(GAINED_TYPES, None)
                # A granted "protection from <colour>" is one key per colour
                # rather than a fixed name, so it is swept by prefix. Listing
                # five keys would work today and be one entry short the day a
                # protection from something other than a colour is granted.
                for key in [
                    k for k in permanent.metadata if k.startswith("protection_from_")
                ]:
                    permanent.metadata.pop(key, None)
                # Layer 6: until-end-of-turn ability grants and removals expire
                # together, in one place, rather than needing a metadata key per
                # keyword listed in _EOT_METADATA_KEYS.
                clear_granted_keywords(permanent, "end_of_turn")
                clear_granted_ability_lines(permanent, "end_of_turn")
                # …and the third channel, a line-derived keyword an effect took
                # away (Barbed Foliage's "it loses flanking until end of turn").
                # Beside its two siblings, because a grant and a removal that
                # share a printed duration have to end at one moment.
                clear_removed_ability_keywords(permanent, "end_of_turn")
                # CR 611.2c: an until-end-of-turn control change ends here too.
                # Dropping the contribution *is* the reversion — the permanent
                # never moved, so whatever contributions remain simply decide
                # again (engine/control.py).
                if end_until_eot_control_changes(permanent):
                    control_reverted = True
                    # "When you lose control of the creature, tap it." (Ray of
                    # Command, Magus of the Unseen.) CR 603.7's delayed trigger,
                    # and this is the moment it watches: the contribution has
                    # just been dropped, so control is lost exactly here. The
                    # marker is cleared with it — the ability triggers once, for
                    # the change that armed it.
                    if permanent.metadata.pop(TAP_WHEN_CONTROL_LOST, False):
                        self.become_tapped(permanent)
        # A control change that ended is a change to who controls what, so the
        # battlefield projection and every derived characteristic are rebuilt —
        # the same pair `change_control`'s callers run when one begins.
        if control_reverted:
            self._sync_control()
            self._recompute_continuous_effects()
        # 610.3: return all creatures exiled "until end of turn" to their owners' battlefields
        returned_from_exile = list(self.exile_until_eot)
        self.exile_until_eot.clear()
        for owner_idx, card_def in returned_from_exile:
            owner = self.players[owner_idx]
            if card_def in owner.exile:
                owner.exile.remove(card_def)
                new_perm = Permanent(card=card_def)
                self._put_permanent_onto_battlefield(owner_idx, new_perm, None)
                self.log.append(f"{card_def.name} returned from exile to {owner.name}'s battlefield")
        self._reset_combat_state(clear_damage_marked=False)
        # CR 514.3a: "…the game checks to see if … any triggered abilities are
        # waiting to be put onto the stack (**including those that trigger 'at
        # the beginning of the next cleanup step'**). If so, … those triggered
        # abilities are put on the stack, then the active player gets priority."
        #
        # Announced here, at the *end* of the step's body, because that is the
        # rule's own order: 514.1's discard and 514.2's sweeps are turn-based
        # actions that happen first, and one of those sweeps is
        # `expire_delayed_triggers` above. A "this turn" ability is therefore
        # already gone when this runs, which is right — it never named this
        # step — while a `next_cleanup_step` entry carries
        # ``until_it_triggers`` and survives to be announced.
        #
        # The stack is then drained where it stands. No priority window opens
        # in this engine's cleanup, so an ability merely enqueued would sit
        # unresolved until the *next* turn's first window: Thawing Glaciers
        # would come back to hand a turn late, on an opponent's upkeep. That is
        # the CR 514.3a window collapsed to its outcome — nobody in this engine
        # holds priority during cleanup to respond in it — and it runs only
        # when something actually fired, so every other turn's cleanup is
        # untouched.
        #
        # CR 514.3a's "another cleanup step begins" is deliberately not
        # modelled: the second pass exists to re-check hand size and
        # state-based actions after the triggers resolved, and no card in the
        # pool can raise a hand over its maximum from a cleanup trigger.
        if fire_delayed_triggers(self, "next_cleanup_step"):
            self._settle()
        self._on_step_or_phase_end(phase, step)
        return cleanup_completed

    def _sacrifice_permanents_cast_at_instant_speed(self) -> None:
        """CR 514.1's half of Mirage's flash-Aura rider.

        "If you cast it any time a sorcery couldn't have been cast, the
        controller of the permanent it becomes sacrifices it at the beginning of
        the next cleanup step." The mark was frozen as the spell was announced
        (`engine/cast_timing.py`) and copied onto the permanent as the spell
        resolved, so nothing here has to reconstruct a timing question the board
        can no longer answer.

        **The next cleanup step, not this permanent's controller's.** CR 514.1
        gives every turn one, and the sentence names the next one there is — so
        an Aura flashed in on an opponent's turn dies at the end of that turn
        rather than surviving to the caster's own.

        Sacrificed rather than destroyed: a regeneration shield does not save it
        and it is its controller's own action (CR 701.17a).
        """
        marked = [
            perm for perm in self.all_permanents()
            if perm.metadata.get(CAST_AT_INSTANT_SPEED)
        ]
        for perm in marked:
            seat = self.controller_index_of(perm)
            if seat is None:
                continue
            self.log.append(
                f"{self.players[seat].name} sacrifices {perm.card.name} "
                "(cast when a sorcery couldn't have been)"
            )
            self.sacrifice_permanent(perm)
