from __future__ import annotations

from ..game_over_guard import goes_no_further

"""Cleanup step (CR 514).

The active player discards down to maximum hand size, then all damage is removed
and "until end of turn" effects end (CR 514.2): regeneration shields, temporary
P/T buffs, damage prevention pools, and the EOT metadata flags. Creatures exiled
"until end of turn" return here (CR 610.3). No player normally receives priority
— unless the step performed a state-based action or put a triggered ability on
the stack, when the active player gets priority and, once everyone has passed
with the stack empty, another cleanup step begins (CR 514.3a).
"""

from ..delayed_triggers import (delayed_mark_events, expire_delayed_triggers,
                                fire_delayed_triggers)
from ..cast_permissions import expire_end_of_turn as expire_end_of_turn_permissions
from ..cast_timing import expire_end_of_turn as expire_end_of_turn_flash
from ..cast_timing import CAST_AT_INSTANT_SPEED
from ..hand_size import maximum_hand_size
from ..models import Permanent
from ..aura_restrictions import clear_ignored_restrictions
from ..cast_bans import clear_ignored_play_bans
from ..keywords import (clear_granted_ability_lines,
                        clear_granted_keywords,
                        clear_removed_ability_keywords,
                        clear_removed_ability_lines,
                        clear_all_abilities_removals)
from ..control import end_until_eot_control_changes
from ..handlers.types import LAND_TYPE_UNTIL_EOT
from ..handlers.control_changes import TAP_WHEN_CONTROL_LOST
from ..land_types import end_land_type_changes_from
from ..type_changes import end_type_changes
from ..mixins._constants import _EOT_METADATA_KEYS
from ..damage_redirects import clear_redirects
from ..land_mana_swaps import clear_swaps as clear_land_mana_swaps
from ..mana_spending import clear_turn_permissions as clear_turn_mana_spending
from ..library_top import clear_reveal_grants
from ..shields import END_OF_TURN, clear_shields
from ..text_changes import end_until_eot_text_changes
from ..turn_replacements import clear_turn_replacements
from ..player_statics import clear_player_keyword_grants
from ..pt import remove_temporary_pt
from ..turn_state import stamped_turn_has_passed


#: How many cleanup steps one turn's cleanup may run (CR 514.3a begins
#: another after each in which a player got priority), and how many times one
#: step gives priority round with the stack empty. A bound on a loop, never a
#: rule: a step that keeps setting something off would otherwise never end.
_MAX_CLEANUP_ROUNDS = 8


def _turn_expired(entries: list, game=None, counted=frozenset()) -> list:
    """*entries* with this cleanup counted against each one's window.

    An entry lasts one turn unless it says otherwise (``remaining_turns``), so
    the list this returns holds exactly the entries whose window outlives the
    turn ending now — with one fewer to go. That is what "this turn and next
    turn" means and what a bare ``clear()`` could not say.

    **A countdown cannot say "during that player's next turn"** (Oracle
    en-Vec): the entry is armed on one turn to take hold on another that may be
    several turns away, and one cleanup subtracted from it would end the
    restriction before it ever applied. Such an entry carries an
    ``on_seat_turn`` stamp instead of a count, and it is dropped by the one
    question a stamp can answer — has the turn it names been and gone
    (``turn_state.stamped_turn_has_passed``). Which is also why *game* is
    optional: the countdown half needs nothing but the entry, and callers
    sweeping a list that has never carried a stamp are unchanged.

    **One count per turn, however many cleanup steps it has.** CR 514.3a
    begins another cleanup step after one in which a player got priority, and
    a countdown is a count of *turns*: Peace Talks' "this turn and next turn"
    counted twice in one turn would end a turn early. *counted* holds (by
    ``id``) the entries the cleanup step before this one in the same turn
    already counted and kept; they are kept as they are. An entry made since —
    a "this turn" restriction cast while a player had priority in cleanup — is
    counted now, and ends.
    """
    kept = []
    for entry in entries:
        window = entry.get("on_seat_turn")
        if window is not None:
            if game is None or not stamped_turn_has_passed(game, window):
                kept.append(entry)
            continue
        if id(entry) in counted:
            kept.append(entry)
            continue
        remaining = int(entry.get("remaining_turns", 1)) - 1
        if remaining > 0:
            kept.append({**entry, "remaining_turns": remaining})
    return kept



class CleanupStepMixin:
    @goes_no_further(True)
    def resolve_cleanup_step(
        self,
        player_index: int,
        discard_hand_indices: list[int] | None = None,
        defer_discard_selection: bool = False,
        *,
        _counted: frozenset = frozenset(),
        _passes: int = 0,
    ) -> bool:
        """The cleanup step (CR 514); True when it ended.

        False while a decision is owed: the hand-size discard a person makes
        (*defer_discard_selection*), or an answer a resolution in the step
        stopped for. *_counted* and *_passes* are this method's own, for the
        cleanup step CR 514.3a begins after one in which a player got
        priority: the countdowns the earlier step counted against the turn
        (:func:`_turn_expired`), and how many steps this turn's cleanup has
        been.
        """
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
        # beginning of the next cleanup step" (Mirage's flash Auras and
        # Visions'). A delayed triggered ability — CR 603.7g: the static
        # ability that let the spell be cast as though it had flash created it
        # as the spell was cast — recorded as a mark on the permanent the
        # spell became (``destruction_events.mark_delayed_destruction``, at
        # ``Game._resolve_card``) and announced as a stack object
        # (``delayed_triggers.delayed_mark_events``). It triggers **now**, as
        # the step begins ("at the beginning of"), so what it names is read
        # off the board before the discard and the sweeps below; it goes on
        # the stack with everything else that triggered once those are done
        # (CR 514.3a). It was a sweep here, sacrificing before anything else
        # in the step and before anybody could answer it.
        cleanup_marks = delayed_mark_events(self, self._cleanup_mark_firings())

        active_player = self.players[player_index]
        cleanup_completed = True
        control_reverted = False
        types_reverted = False
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
                    # Nobody named the cards: the ones the player least wants
                    # to hold (``ai_prompt_picks.hand_size_discards``), hand
                    # order between equals — it was the first cards in hand.
                    from ..ai_prompt_picks import hand_size_discards

                    hand = active_player.hand
                    for discarded in [
                        hand[slot] for slot in hand_size_discards(self, player_index, excess)
                    ]:
                        if self.take_card_from_hand(active_player, discarded):
                            self._discard_card(active_player, discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")

        # "Target player skips their next combat phase **this turn**." (Moment
        # of Silence.) CR 514.2 closes the window the card named; the record is
        # already inert past its stamp, so this is the sweep for what nobody
        # came back for — beside the "this turn" clears below rather than
        # anywhere else, so every turn-bounded record ends in one place.
        self.expire_stamped_phase_skips()
        self.combat_damage_prevented_until_eot = False
        self.combat_damage_prevented_by = []
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
        # CR 514.2 again, one axis over: a "this turn" *timing* grant ends
        # here too (Winding Canyons). Beside the zone sweep rather than in
        # it, because the two records answer different questions.
        expire_end_of_turn_flash(self)
        # "…can't block this turn" blanket restrictions end with the turn too.
        self.blocking_restrictions_until_eot = _turn_expired(
            self.blocking_restrictions_until_eot, self, _counted
        )
        # "Creatures can't attack this turn." (Festival.) CR 514.2 ends it with
        # the same cleanup, beside its blocking twin rather than anywhere else,
        # so the two cannot come to disagree about when "this turn" is over.
        #
        # "This turn **and next turn**" (Peace Talks) is the same restriction
        # over a longer window, so the sweep *counts down* rather than clearing:
        # an entry arrives carrying how many cleanups it survives, and the
        # default of one is every entry written before that existed. A second
        # list for the two-turn case would be a second place to ask when a
        # restriction ends.
        self.attack_restrictions_until_eot = _turn_expired(
            self.attack_restrictions_until_eot, self, _counted
        )
        # The same countdown for the targeting ban Peace Talks' other clause
        # arms, read by `legality_enumeration._enumerate_targets`.
        self.targeting_bans = _turn_expired(self.targeting_bans, self, _counted)
        # "Until the end of your next turn, they can't phase in." (Teferi,
        # Timeless Voyager.) The block counts the *caster's* turn ends; this
        # cleanup ends the active player's turn, so their countdowns tick —
        # once per turn, as the lists above count (``_counted``).
        counted_blocks = []
        for player in self.players:
            for perm in player.phased_out:
                block = perm.metadata.get("phase_in_blocked")
                if (
                    isinstance(block, dict)
                    and id(block) not in _counted
                    and block.get("seat") == self.active_player_index
                    and int(block.get("turn_ends_remaining", 0)) > 0
                ):
                    block["turn_ends_remaining"] = int(block["turn_ends_remaining"]) - 1
                    counted_blocks.append(block)
        # What this step counted against the turn, for the cleanup step CR
        # 514.3a may begin after it (the entries the lists kept, by id: each
        # list still holds them, so the ids stay theirs).
        counted = frozenset(
            {id(entry) for entry in self.blocking_restrictions_until_eot}
            | {id(entry) for entry in self.attack_restrictions_until_eot}
            | {id(entry) for entry in self.targeting_bans}
            | {id(block) for block in counted_blocks}
            | set(_counted)
        )
        for player in self.players:
            # CR 615.3: every prevention shield lasts until it is used up or its
            # duration expires, and "until end of turn" expires here. One sweep
            # over the collection rather than a line per card-named field —
            # which is also why a new kind of shield needs no line here.
            clear_shields(player)
            # CR 614.9's redirects expire with the turn for the same reason and
            # by the same one sweep (engine/damage_redirects.py).
            clear_redirects(player)
            # …and so do the replacements a resolving spell armed for the turn
            # (Blind Fury, Equal Treatment, Plagiarize — CR 514.2), one sweep
            # over the record rather than a line per card: not at the end of
            # combat, because each sentence names the turn.
            clear_turn_replacements(player)
            # "Until end of turn, if you tap a land you control for mana, it
            # produces {U} instead of any other type." (Deep Water.) A CR 611.2
            # swap with a printed window, and it expires by the same one sweep
            # for the same reason (engine/land_mana_swaps.py).
            clear_land_mana_swaps(player)
            # "You gain shroud until end of turn." (Gilded Light.) A keyword a
            # resolving spell gave the seat itself (CR 702.18a's "or player"),
            # ended by the same sweep for CR 514.2's reason
            # (engine/player_statics.py).
            clear_player_keyword_grants(player)
            # "Until end of turn, for as long as that card remains on top of
            # your library, play with the top card of your library revealed."
            # (Temporal Aperture.) CR 611.2a's half of that compound duration —
            # the other half needs no sweep at all, because every read of the
            # record re-asks whether the named card is still on top
            # (engine/library_top.grant_holds).
            clear_reveal_grants(player, END_OF_TURN)
            player.mirror_damage_charges = 0
            player.mirror_damage_sources = []
            player.channel_active_until_eot = False
            # "For one spell **this turn**" (North Star): an unused permission
            # expires with the turn, the same way an unused regeneration shield
            # below does.
            player.spend_mana_as_though_grants = []
            # "**Until end of turn**, you may spend white mana as though it
            # were mana of any color." (False Dawn.) A permission with a window
            # (CR 611.2a), ended by the record leaving — and the seat's derived
            # list is rebuilt at once, because every payment site reads that
            # list and a permission left in it would outlive its turn.
            if clear_turn_mana_spending(player):
                self._refresh_mana_spending()
            player.prevent_one_damage_emblems = []
            # **Phased-out permanents too.** CR 514.2 names them — "all damage
            # marked on permanents (including phased-out permanents) is
            # removed and all 'until end of turn' … effects end" — and
            # CR 702.26f says what that means for them: an effect that expires
            # while its permanent is phased out no longer affects it once it
            # phases in. This walked the battlefield alone, so a Giant Growth
            # on a creature Reality Ripple then phased out came back with its
            # +3/+3 for the whole of its controller's next turn (and the AI,
            # rehearsing the engine faithfully, priced a trample grant in
            # response to the Ripple as a lasting one).
            phased_out = list(player.phased_out)
            for permanent in [*self.controlled_by(player), *phased_out]:
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
                #
                # …and a type that ended is a permanent a type-scoped effect
                # now reaches or no longer does. "Target creature becomes that
                # type until end of turn" (Unnatural Selection) made a Bear a
                # Goblin under a Goblin King: the lord's +1/+1 is a cached
                # buff, so the record leaving has to re-derive it — the reason
                # the text-change sweep below recomputes, one layer over.
                if end_type_changes(
                    permanent,
                    lambda record: record.get("duration") == "until_end_of_turn",
                ):
                    types_reverted = True
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
                # "**Until end of turn**, this creature loses "<ability>"."
                # (Glittering Lion.) The printed-line removal, swept with its
                # keyword twin for the same reason.
                clear_removed_ability_lines(permanent, "end_of_turn")
                # "**Until end of turn**, target creature loses all
                # abilities …" (Humble.) The fourth removal channel, swept
                # beside the third and at the same moment: a blanket that
                # outlived its window would leave a vanilla creature for the
                # rest of the game.
                clear_all_abilities_removals(permanent, "end_of_turn")
                # CR 116.2d's suspension: "…to ignore this effect **until end
                # of turn**" (Volrath's Curse). The same printed duration in a
                # fourth channel, swept beside the other three because a
                # duration means one moment however it was bought.
                clear_ignored_restrictions(permanent)
                # …and the board-wide half of the same subrule (Damping
                # Engine), swept beside it because one printed duration ends at
                # one moment however the offer was shaped.
                clear_ignored_play_bans(permanent)
                # "Change the text of target permanent … **until end of turn**."
                # (Whim of Volrath.) CR 612's rewrite with a printed duration —
                # the first in the pool — and it is filtered rather than popped
                # for the gained-type sweep's reason a few lines up: the key
                # holds records of two lifetimes, and popping it whole would end
                # Magical Hack's permanent rewrite with the turn. A land word
                # inside a lord's grant line is part of a cached buff, so
                # dropping the record has to re-derive it, exactly as making one
                # does.
                if end_until_eot_text_changes(permanent):
                    self._recalculate_lord_buffs()
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
                    if permanent.metadata.pop(TAP_WHEN_CONTROL_LOST, False) and not any(
                        permanent is out for out in phased_out
                    ):
                        # …but a phased-out permanent "can't affect or be
                        # affected by anything else in the game" (CR 702.26b).
                        self.become_tapped(permanent)
        # A control change that ended is a change to who controls what, so the
        # battlefield projection is rebuilt — and then, **whatever ended**,
        # every derived characteristic (CR 514.2 ends the turn's effects; CR
        # 611.3a re-asks each static what it applies to). The recompute used
        # to be inside the branch, for a control change alone, so a turn-long
        # recolour, type or keyword that ended here left the statics judged
        # against the turn that had just finished: a Bears made white by
        # Heaven's Gate kept a Crusade's +1/+1 as a green creature until the
        # next state-based check, a turn later.
        if control_reverted:
            self._sync_control()
        self._recompute_continuous_effects()
        # 610.3: return all creatures exiled "until end of turn" to their owners' battlefields
        returned_from_exile = list(self.exile_until_eot)
        self.exile_until_eot.clear()
        # CR 514.2: every "until end of turn" effect ends at once, so what they
        # exiled returns in one event (CR 610.3d, 603.6a).
        with self.entering_together():
            for owner_idx, card_def in returned_from_exile:
                owner = self.players[owner_idx]
                # Through the departure seam: it locates the copy by identity where
                # ``card_def in owner.exile`` / ``.remove(card_def)`` compared by
                # value and would have reached a look-alike printing, and it retires
                # the exile register with the card (CR 400.7).
                if self.take_card_from_exile(owner_idx, card_def):
                    new_perm = Permanent(card=card_def)
                    self._put_permanent_onto_battlefield(owner_idx, new_perm, None)
                    self.log.append(f"{card_def.name} returned from exile to {owner.name}'s battlefield")
        self._reset_combat_state(clear_damage_marked=False)
        # CR 514.3a's first half: "the game checks to see if any state-based
        # actions would be performed" once 514.1's discard and 514.2's sweeps
        # are done — and if so performs them, before the triggered abilities
        # below go on the stack. An "until end of turn" effect ending is a
        # state change: a Grizzly Bears Giant Growth kept alive under an
        # Enfeeblement is a 0/0 now (CR 704.5f), and a creature Ray of Command
        # stole goes home to a controller holding its namesake (CR 704.5j).
        # This step checked only when something had triggered, so those waited
        # for the next turn's untap step — and died on the wrong turn, after
        # `begin_turn_bookkeeping` had already reset this one's death counts.
        #
        # And a check that performed anything is half of the exception: "If
        # so, those state-based actions are performed, then those triggered
        # abilities are put on the stack, **then the active player gets
        # priority**" — with or without a trigger.
        performed = self._check_after_turn_based_actions()
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
        # Then the active player gets priority, and the step's window is run
        # where it stands (``_settle``): a table whose seats a driver plays
        # (the simulator's ``priority_driver``) gives each seat priority
        # before each object resolves and once more with the stack empty, so
        # the sacrifice of a flashed-in Aura can be answered; a table with an
        # interactive seat still has the window collapsed to its outcome here
        # — the web layer holds no cleanup window (``web/game_flow.
        # _advance_phase``'s ``step == "end"`` branch) — and so does a bare
        # headless one. An ability merely enqueued would otherwise sit
        # unresolved until the *next* turn's first window: Thawing Glaciers
        # would come back to hand a turn late, on an opponent's upkeep.
        #
        # **And whatever else triggered during the step.** The hand-size
        # discard above is the other way something reaches the stack here: a
        # card with madness discarded to it is exiled and its trigger
        # announced (CR 702.35a — the card's ruling of 2022-12-08: "You could
        # discard it … because you have too many cards in your hand during
        # your cleanup step"), and "whenever an opponent discards a card"
        # (Megrim) fires off the same discard. Both waited on the stack into
        # the next turn while only the delayed triggers were settled here.
        #
        # The marks that triggered as the step began (above) go on the stack
        # here with them, in the same batch order the end step uses: the
        # marks first.
        if cleanup_marks:
            self._enqueue_triggered_batch(cleanup_marks)
        fired = fire_delayed_triggers(self, "next_cleanup_step")
        if performed or fired or self.stack:
            self._settle()
            for _ in range(_MAX_CLEANUP_ROUNDS):
                if self.stack or self.waiting_prompt() is not None:
                    # A person owes the answer (the madness offer, held on the
                    # stack for them): the step is not over, and the caller
                    # must not begin the next turn around it.
                    self._on_step_or_phase_end(phase, step)
                    return False
                # CR 514.3a / 117.4: "Once the stack is empty and all players
                # pass in succession" — each player has priority once more
                # with nothing on the stack, and what one casts there resolves
                # in this step before it ends (``offer_priority``; inert but
                # at a driver's table).
                if self.is_game_over() or not self.offer_priority():
                    break
                self._settle()
            # "…another cleanup step begins": 514.1's discard and 514.2's
            # sweeps again, for whatever the window changed — a hand a
            # madness card drew into (an Obsessive Search discarded to hand
            # size is cast and draws a card), damage dealt and "until end of
            # turn" effects created in the window, a flash Aura cast there
            # (its "next cleanup step" is that one). The countdowns this step
            # counted are not counted again (*counted*). Bounded, as a step
            # that keeps setting something off would otherwise never end.
            self._on_step_or_phase_end(phase, step)
            if self.is_game_over():
                return cleanup_completed
            if _passes + 1 >= _MAX_CLEANUP_ROUNDS:
                self.log.append(
                    f"cleanup stopped after {_passes + 1} cleanup steps (possible loop)"
                )
                return cleanup_completed
            return self.resolve_cleanup_step(
                player_index, defer_discard_selection=defer_discard_selection,
                _counted=counted, _passes=_passes + 1,
            )
        self._on_step_or_phase_end(phase, step)
        return cleanup_completed

    def _cleanup_mark_firings(self) -> list:
        """Every delayed ability recorded as a mark that triggers as this
        cleanup step begins, as ``(permanent, mark, rider)`` for
        ``delayed_triggers.delayed_mark_events``: Mirage's flash-Aura rider
        (:data:`~engine.cast_timing.CAST_AT_INSTANT_SPEED`).

        A sacrifice with **no** sacrificer recorded: "**the controller of the
        permanent it becomes** sacrifices it" is whoever controls the Aura as
        the ability resolves, where "sacrifice it" would be the ability's own
        controller (CR 701.21a; ``handlers/delayed.carry_out_delayed_mark``).
        Sacrificed rather than destroyed: a regeneration shield does not save
        it.

        **The next cleanup step, not this permanent's controller's.** CR 514.1
        gives every turn one, and the sentence names the next one there is —
        so an Aura flashed in on an opponent's turn dies at the end of that
        turn rather than surviving to the caster's own.

        Over each seat's permanents through the control seam, as the end
        step's marks are (``_end_step_mark_firings``), so a phased-out
        permanent's mark waits, as the sweep this replaces did.
        """
        return [
            (permanent, CAST_AT_INSTANT_SPEED, {"action": "sacrifice"})
            for controller in self.players
            for permanent in self.controlled_by(controller)
            if permanent.metadata.get(CAST_AT_INSTANT_SPEED)
        ]
