"""``Game``'s general helpers: the small questions every step asks.

Summoning sickness (CR 302.6) and whether a permanent entered this turn; the
step and phase boundaries - effects tagged to expire at one, and mana pools
emptied between steps (CR 500.4-500.5); a spell's colours on the stack; a
reveal's structured record; the recompute's one entry point,
``_recompute_continuous_effects`` (CR 611.3a); phasing (CR 702.26); and the
two places a permanent's tapped status changes, ``become_tapped`` and
``become_untapped`` (CR 701.26).

This module was one 4,386-line class. What else it held is one mixin each,
composed onto ``Game`` immediately after ``GameHelpersMixin``:

    control_seam          ControlSeamMixin          who controls what (CR 613
                                                    layer 2), addressing one
                                                    permanent, leaving the
                                                    battlefield
    zone_funnels          ZoneFunnelsMixin          the doors into a hand, a
                                                    library, a graveyard and out
                                                    of exile; entering the
                                                    battlefield
    deaths                DeathsMixin               destruction, sacrifice, the
                                                    move to a graveyard, the
                                                    dies triggers
    target_announcements  TargetAnnouncementsMixin  putting an object on the
                                                    stack and announcing what it
                                                    targets

They are disjoint (no method is defined twice, none calls ``super()``), so
their order among themselves carries no meaning; each reaches the others
through ``self``.
"""

from __future__ import annotations

from ..delayed_triggers import (end_source_tapped_delayed_triggers,
                                fire_delayed_triggers)
from ..enter_effects import ENTERED_BATTLEFIELD_TURN
from ..events import emit
from ..linked_exile import UNTAPPED
from ..models import Permanent
from ..phasing_locks import phase_out_forbidden
from ._constants import _MANA_SYMBOLS, _NO_PRIORITY_STEPS


class GameHelpersMixin:
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

    def _stack_item_colors(self, item) -> tuple[str, ...]:
        """Effective color symbols of a spell on the stack.

        Two effects can move it, in this order. A Lace card's recolour
        (``StackItem.choices["color_override"]``) is on the object itself and
        wins, because it was applied to this spell; a board-wide static ("The
        same is true for **spells you control**", Celestial Dawn) is read off
        the board under it, so a Lace resolved onto one spell is not undone by
        an enchantment that recolours every spell its controller casts.

        **Not** ``choices["new_color"]``, which this read until PCY W3G2. That
        key is what a spell or ability was *announced* with — a text change's
        replacement word (Sleight of Mind), an any-one-colour mana spell's
        colour (Metamorphosis) — and reading it here made every such object that
        colour on the stack: a blue Sleight of Mind cast to write "red" was a
        red spell, which Blue Elemental Blast ("counter target red spell")
        could counter and Red Elemental Blast could not. What an effect did to
        the object and what its
        controller said about its effect are two facts, so they are two keys.

        An instance method since Mirage -- it was a ``staticmethod`` and every
        call site already passed through ``self``/``game``, so the board became
        askable without touching one of them.
        """
        # ``is not None``: a spell made colourless has no colours (CR 105.2c)
        # and that is an answer. The record was returned as stored, so Ersatz
        # Gnomes' "target spell becomes colorless" made a spell the colour
        # ``"colorless"`` — a non-empty answer to every reader asking whether
        # it has one.
        from ..color_changes import spell_color_change

        recolored = spell_color_change(item)
        if recolored is not None:
            return recolored
        from ..object_colors import card_colors

        return tuple(card_colors(
            self, item.card, getattr(item, "caster_index", None)
        ))

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

    def entered_this_turn(self, permanent: Permanent) -> bool:
        """Whether *permanent* entered the battlefield during the current turn.

        A different question from :meth:`_controlled_since_turn_start`, and the
        pair is why both records exist: that one is CR 302.6's "since their most
        recent turn began", which a control change resets and a passing turn
        carries forward, while this is a plain fact about arrival that nothing
        rewrites. A permanent that changed hands this turn has not been
        controlled since the turn began and did *not* enter this turn, and Chaos
        Lord is the card that tells them apart.

        A permanent with no stamp did not enter through the entry path at all —
        a test fixture placed straight onto a battlefield — and answers no,
        which is the reading that leaves such a fixture behaving like a
        permanent that has been there all along.
        """
        return permanent.metadata.get(ENTERED_BATTLEFIELD_TURN) == self.turn

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
        Lord of Atlantis, Castle) and dynamic P/T (Nightmare) reflect the new board.

        **Board-wide statics are recorded first**, and that is CR 613's layer
        order rather than a convenience. A static that removes abilities
        (Humility, layer 6) decides whether a lord's anthem exists at all before
        layer 7c can apply it — and `_recalculate_lord_buffs` reads each source's
        *effective* card, which is where the removal lands. Recorded second, as
        it was, that read saw the previous pass's answer: a Lord of Atlantis
        played into a Humility went on buffing for one whole recompute, which is
        long enough for anything that reads P/T in between. Idempotent, so the
        second recording inside `_refresh_dynamic_creatures` — which has to run
        *after* layer 4's land animation, so a creature-scoped static sees the
        lands this pass animated — still stands.
        """
        self._refresh_global_statics(list(self.all_permanents()))
        self._recalculate_lord_buffs()
        self._refresh_dynamic_creatures()

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
        # "Target permanent **can't phase out**." (Spatial Binding, CR 702.26.)
        # Asked here, at the one transition every phase-out passes through, and
        # not only at the untap step's alternation: an activated phase-out
        # (Mist Dragon, Vaporous Djinn, Frenetic Efreet) and a one-shot
        # (Reality Ripple, Taniwha) are the other ways a permanent leaves, and a
        # lock enforced at the alternation alone is one the target's controller
        # escapes by activating an ability.
        if phase_out_forbidden(permanent):
            self.log.append(f"{permanent.card.name} can't phase out")
            return False
        moving = [permanent] + [
            aura
            for aura in list(permanent.metadata.get("attached_auras") or [])
            if self.is_on_battlefield(aura)
        ]
        # Announced **before** the permanent leaves, because the ability is its
        # own: `iter_triggered_abilities` scans battlefields, and a permanent
        # that has already phased out is on none — so Teferi's Imp's "whenever
        # this creature phases out" would watch its own departure and miss it.
        # The trigger goes on the stack while the source is still there and
        # resolves after it is gone, which is CR 603.6's ordinary shape for an
        # ability that watches its own object leave.
        #
        # CR 702.26g's indirect half is not announced: "abilities that trigger
        # when a permanent becomes attached or unattached … don't trigger when
        # that permanent phases in or out" (702.26j), and an Aura dragged along
        # by its host did not phase out on its own account. Only the permanent
        # the caller named did.
        self._announce_phasing("phases_out", [permanent])
        # CR 702.26d: not a zone change. The battlefield lists and the combat
        # maps move exactly as they do for a removal — which is why this goes
        # through the one transition — and none of leaving's *consequences*
        # happen: no leaves-the-battlefield trigger, and the Auras in ``moving``
        # stay attached so they phase back in still enchanting the host
        # (CR 702.26g/702.26i). Detaching them, which the ordinary removal does,
        # made Vanishing bin itself every time it was activated.
        self.remove_all_from_battlefield(moving, zone_change=False)
        for perm in moving:
            perm.metadata["phased_out"] = True
            self.players[controller].phased_out.append(perm)
            self.log.append(f"{perm.card.name} phased out")
        self._recompute_continuous_effects()
        return True

    def resolve_phasing_for(self, seat: int) -> None:
        """CR 702.26a's phasing event, both halves, at *seat*'s untap step.

        "During each player's untap step, before the active player untaps
        permanents, all phased-in permanents with phasing that player controls
        'phase out.' **Simultaneously**, all phased-out permanents that had
        phased out under that player's control 'phase in.'"

        The simultaneity is why this is one method rather than two calls in a
        row: a permanent that phases out here must not be swept straight back
        in by the other half, and one that phases in must not phase out again
        the moment it arrives. So both sets are read off the board before
        either is applied — which is also the whole of CR 702.26a's alternation,
        with no per-permanent flag to keep in step.

        The keyword is the only input to the outgoing half, so a permanent that
        *gained* phasing (Teferi's Curse, Shimmer) leaves on the next untap step
        and one that lost it stays. The incoming half reads the holding list
        instead, which is what makes a permanent phased out by a one-shot effect
        (Reality Ripple) come back exactly once.
        """
        player = self.players[seat]
        leaving = [
            perm for perm in self.controlled_by(seat)
            if self._has_keyword(perm, "phasing")
            and not phase_out_forbidden(perm)
        ]
        # The lock is asked twice on purpose. Here it keeps a locked permanent
        # out of the set the event reads, which is what CR 702.26a's
        # simultaneity needs — a permanent excluded after the sets were taken
        # would still have been counted as leaving. `phase_out_permanent` asks
        # again for every *other* way a permanent phases out. Until Spatial
        # Binding this read had **no writer anywhere in the engine**, so a
        # restriction arriving would have been half enforced.
        arriving = list(player.phased_out)
        self.phase_in_for(seat, permanents=arriving)
        for perm in leaving:
            self.phase_out_permanent(perm)

    def phase_in_for(self, seat: int, *, permanents: list[Permanent] | None = None) -> None:
        """CR 702.26c: phased-out permanents *seat* controls phase in — the same
        object, no new permanent_id, no enters-the-battlefield anything. A
        ``phase_in_blocked`` marker (Teferi, Timeless Voyager's rider) holds a
        permanent out until its countdown expires.

        *permanents* is the set the phasing event already read (see
        :meth:`resolve_phasing_for`); absent, it is whatever is held right now.
        Matched **by identity**, because two copies of one card in a holding
        list are equal by value and a membership test would phase in the wrong
        one — the same reason the control seam bans ``.remove()`` on a
        battlefield.
        """
        player = self.players[seat]
        if not player.phased_out:
            return
        chosen = (
            None if permanents is None else {id(perm) for perm in permanents}
        )
        staying: list[Permanent] = []
        returning: list[Permanent] = []
        for perm in player.phased_out:
            block = perm.metadata.get("phase_in_blocked")
            if (chosen is not None and id(perm) not in chosen) or (
                isinstance(block, dict) and int(block.get("turn_ends_remaining", 0)) > 0
            ):
                staying.append(perm)
                continue
            perm.metadata.pop("phased_out", None)
            perm.metadata.pop("phase_in_blocked", None)
            player.battlefield.append(perm)
            returning.append(perm)
            self.log.append(f"{perm.card.name} phased in")
        player.phased_out = staying
        self._recompute_continuous_effects()
        self._announce_phasing("phases_in", returning)

    #: The joined kind a phasing announcement makes **beside** its own. "When
    #: this creature **phases out or leaves the battlefield**, mill three cards"
    #: (Ertai's Familiar) is CR 603.1's one ability with two trigger events, and
    #: the engine's answer to that shape is one condition kind read at both fire
    #: sites — the arrangement `creature_attacks_or_blocks` already has, where
    #: the two declaration steps each name it in their scan.
    #:
    #: A second announcement rather than a second row in a scan, because this
    #: half goes through `emit`, and `collect` gathers exactly one kind. A table
    #: rather than a branch, so the phase-*in* half cannot be given a joined
    #: kind nothing announces by somebody editing the wrong line: there is no
    #: printed "phases in or leaves the battlefield", and a card leaving the
    #: battlefield has not phased in.
    _JOINED_PHASING_KINDS: dict[str, str] = {
        "phases_out": "phases_out_or_leaves_battlefield",
    }

    def _announce_phasing(self, kind: str, permanents: list[Permanent]) -> None:
        """CR 603.2's "whenever this permanent phases in / out" triggers.

        One announcement per permanent, from the two seams that move one — so a
        card watching the event is fired by the untap step's alternation, by a
        one-shot phase-out and by anything else that reaches those two methods,
        without any of them knowing the trigger exists. That is the arrangement
        `tests/engine/test_trigger_dispatchers.py` exists to force: a condition
        parsed by both front ends and announced by nothing is a card that
        compiles supported and does nothing.
        """
        from ..events import emit

        for perm in permanents:
            # A permanent that has just phased *out* is on no battlefield, so
            # the control seam cannot answer — `base_controller_index` is the
            # seat it entered under and is never rewritten, which is the same
            # fallback `mixins/effects.py` uses for a source that has left.
            seat = self.controller_index_of(perm)
            if seat is None:
                seat = perm.metadata.get("base_controller_index")
            emit(self, kind, subject=perm, source_seat=seat)
            joined = self._JOINED_PHASING_KINDS.get(kind)
            if joined is not None:
                emit(self, joined, subject=perm, source_seat=seat)

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
            # controller ("destroy it" — Mine Layer) reads it here, frozen at the
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
        # "When this creature **becomes untapped** or you lose control of this
        # creature, exile that creature." (Coffin Queen.) The first half of the
        # other pairing, announced beside the one above and under its own key:
        # an entry armed for one pairing must not be woken by the other's name,
        # which is why these are two calls rather than a list of aliases.
        fire_delayed_triggers(
            self, "bound_permanent_untaps_or_control_lost", subject=permanent,
        )
        # "**For as long as this creature remains tapped,** …" (Giant Oyster).
        # The same moment read the other way round: the abilities *this*
        # permanent created under that duration end now, because the condition
        # has stopped holding (CR 611.2b). Beside the announcement above for the
        # reason it is here — this is the one place a permanent becomes
        # untapped — and it ends them outright rather than leaving them to be
        # skipped, because a "for as long as" duration does not start again.
        end_source_tapped_delayed_triggers(self, permanent)
        # The other record the same duration governs: "it doesn't untap during
        # its controller's untap step **for as long as this creature remains
        # tapped**" (Phyrexian Gremlins, and Giant Oyster's first clause). Ended
        # here for the reason above and not merely skipped while the holder is
        # untapped — a record left in place re-locked the permanent the next
        # time the holder tapped for any reason at all. Imported locally, the
        # way the handler read in ``zone_funnels.py`` is: a mixin composed onto
        # `Game` sits under the handlers that dispatch through it.
        from ..handlers.tapping import end_untap_lock

        end_untap_lock(permanent)
        # "When this artifact leaves the battlefield **or becomes untapped**,
        # return that exiled card…" (Tawnos's Coffin). The second of the two
        # things that end a linked exile, and it is here for the reason the
        # first is in `remove_from_battlefield`: this is the one place a
        # permanent becomes untapped, so a return wired into any single untapper
        # would be a return the other ten forgot.
        self.return_linked_exile(permanent, "became untapped", UNTAPPED)
        return True
