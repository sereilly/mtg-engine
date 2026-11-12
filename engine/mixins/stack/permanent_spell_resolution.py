"""A permanent spell resolving (CR 608.3): the permanent it becomes, and its
entry.

``_resolve_card`` resolves a spell's card, and a card that becomes a
permanent — a creature, an artifact, an enchantment, a planeswalker, or a
land being played (CR 305.1) — goes down ``_resolve_permanent_spell``: the
``Permanent`` is built, stamped with what the cast decided and the spell
carried, and put onto the battlefield through
``_put_permanent_onto_battlefield``. Every stamp is written before the
entry, because an entry replacement (CR 614.1c) and a characteristic-defining
ability read the permanent as it arrives, so a record a cast makes for the
permanent it will become is stamped here, from the stack item's ``choices``.
What watches the entry — its log line, its entry trigger, an Aura's
attachment, a land play's announcement — is the entry's ``then``.

Split out of ``resolution.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``StackResolutionMixin``; the step is moved
out of ``_resolve_card`` whole and called from it in its place.
"""

from __future__ import annotations

from ...auras import aura_enchant_clause
from ...cast_costs import (
    CAST_COST_DISCARD_MANA_VALUE, KICKED, kicked, KICKED_WITH, kickers_paid,
)
from ...cast_timing import CAST_AT_INSTANT_SPEED
from ...color_changes import carry_spell_color_change
from ...destruction_events import mark_delayed_destruction
from ...enter_effects import COPY_DECLINED, copy_on_enter_type
from ...entry_awaiting import entry_happened
from ...events import emit
from ...game_types import first_target_id, single_slot
from ...models import Permanent
from ...oracle import compile_card_oracle
from ...prevention.shields import carry_spell_shields_onto_permanent
from ...sunburst import MANA_SPENT_TO_CAST
from ...text_changes import carry_spell_text_changes


class PermanentSpellResolutionMixin:
    def _resolve_permanent_spell(
        self, *, card, cast_from_zone, caster, caster_index, choices, owner,
        owner_seat, primary_type, stack_target, target_graveyard_card,
        target_permanent_id, target_permanent_index, target_player_index,
        text_card, text_change_effects, x_value,
    ):
        """A permanent spell resolving (CR 608.3), or a land being played
        (CR 305.1) down the same road: the permanent it becomes, and its entry.

        The ``Permanent`` is built and stamped with what the cast decided and
        the spell carried — the X, a copy choice, the zone it was cast from, a
        colour, text or prevention effect that applied to the spell (CR 400.7a,
        400.7c), kicked and with which kicker, a discarded card's mana value, a
        flash Aura's cleanup sacrifice, the chosen creature type, its owner
        (CR 108.3) — every stamp before the entry, because an entry replacement
        (CR 614.1c) and a characteristic-defining ability read the permanent as
        it arrives. Then a land play's count, the entry, and what watches it
        (``arrived``), at once or at the last answer an "as it enters" choice
        owes.

        The permanent arm of ``_resolve_card``, moved out of it whole and
        called from it in its place: "above" and "below" in its comments are
        places in the resolution as that method runs it.
        """
        permanent = Permanent(card=card)
        if x_value is not None:
            permanent.metadata["cast_x_value"] = x_value
        # A "copy as it enters" permanent (Clone) records the chosen copy
        # target so initialization can copy the player-selected creature
        # rather than an arbitrary one — with the id the stack stamped
        # beside the slot, because the slot is a position the board may
        # have renumbered since the cast (``_resolve_copy_target``). **An
        # id alone is a choice too**: a cast that named the creature by
        # ``target_permanent_ids`` and no slot recorded nothing here, and
        # a Clone aimed at a Brass Herald copied whatever creature came
        # first on the board (a Soul Warden).
        #
        # **A declined copy is a choice too** (``enter_effects.
        # COPY_DECLINED``): "You can choose not to copy anything", and a
        # cast that said so entered as a copy of the first creature on the
        # board all the same, because no target read as "nobody chose".
        if (choices or {}).get(COPY_DECLINED):
            permanent.metadata[COPY_DECLINED] = True
        elif (
            target_permanent_index is not None
            or first_target_id(target_permanent_id) is not None
        ):
            permanent.metadata["copy_target"] = (
                target_player_index if target_player_index is not None else caster_index,
                single_slot(target_permanent_index),
                first_target_id(target_permanent_id),
            )
        # The one entry site in the engine that *is* a cast (CR 701.5a):
        # a permanent spell resolving. Every other path puts a permanent
        # onto the battlefield without casting it, which is what
        # Containment Priest reads.
        # "…or you cast it **from your graveyard**" (Archfiend's Vessel).
        # The zone the spell was cast from, which for a permanent spell is
        # also the zone the permanent came from — one call, two records,
        # because a later card may ask either question and they are not the
        # same one: a reanimation stamps the first and not the second.
        permanent.metadata["cast_from_zone"] = cast_from_zone
        # CR 400.7a: an effect that changed this spell's colour on the
        # stack "continue[s] to apply to the permanent that spell
        # becomes". The spell's record ended with the spell, so a Lace cast
        # at a Grizzly Bears spell logged "became R" and put a green Bears
        # onto the battlefield (the five Laces and Ersatz Gnomes). Carried
        # here for the reason the kicked stamp below is: before the
        # permanent enters, so whatever reads its colour as it arrives
        # reads the colour it arrives with — and with the effect's own
        # duration and timestamp (``color_changes``).
        carry_spell_color_change(choices, permanent)
        # …and its text twin (the rulings: "the permanent will retain the
        # text change until the effect wears off"), before the entry.
        carry_spell_text_changes(text_change_effects, permanent)
        # CR 400.7c, its prevention twin: "Prevention effects that apply to
        # damage from a permanent spell on the stack continue to apply to
        # damage from the permanent that spell becomes" — a shield hung on
        # this cast's stack item ("Prevent all damage target spell would
        # deal this turn", Shieldmage Elder) is carried before the entry,
        # so an entry trigger's damage is already covered.
        if self.resolving_items:
            carry_spell_shields_onto_permanent(
                self.resolving_items[-1], permanent, self
            )
        # "If this creature **was kicked**, it enters with …" / "When this
        # creature enters, **if it was kicked**, …" / "…if this creature
        # **wasn't kicked**, sacrifice it" (Skizzik, turns later). CR
        # 702.33d settled the answer at the announcement and the stack item
        # carried it; it is copied onto the permanent here because the
        # permanent is what all three sentences are asked of and the stack
        # item is gone by the time the last of them is.
        #
        # Stamped **before** the permanent enters, for the creature type's
        # reason below: an entry replacement (CR 614.1c) reads it as the
        # permanent arrives. And only here, the one entry that is a cast
        # (CR 701.5a) -- a reanimated, blinked or token-copied permanent
        # never passes this line, which is the rule rather than an
        # omission: it was not cast, so it was not kicked.
        if kicked(card, choices):
            permanent.metadata[KICKED] = True
            # ...and **which** of its kicker costs paid for it
            # (CR 702.33b: a Battlemage prints two). "If it was kicked with
            # its {1}{G} kicker" is CR 702.33f's question about one of
            # them, asked of the permanent for the same reason the flag
            # above is. A tuple of the recorded keys, so the entry trigger
            # and the announcement that paid name a cost by one string.
            permanent.metadata[KICKED_WITH] = kickers_paid(card, choices)
        # "…where X is **the discarded card's mana value**." (Dralnu's
        # Pet.) What the spell's cost discarded, as the one number an entry
        # replacement may read back — see
        # ``cast_costs.CAST_COST_DISCARD_MANA_VALUE`` for why it is the
        # number and why it is stamped here. Exactly one card, or no
        # stamp: "the discarded card" names nothing else.
        # "…a +1/+1 counter on it for each color of mana spent to cast it"
        # (sunburst, CR 702.44a). What the cast's payment spent, measured as
        # it paid (``sunburst.MANA_SPENT_TO_CAST``), stamped for the entry
        # replacement that reads it as the permanent arrives -- the kicked
        # stamp's place and reason: only a permanent spell resolving passes
        # this line, so a permanent put onto the battlefield any other way
        # enters with no sunburst counters (CR 702.44b).
        mana_spent = (choices or {}).get(MANA_SPENT_TO_CAST)
        if mana_spent:
            permanent.metadata[MANA_SPENT_TO_CAST] = dict(mana_spent)
        cost_discards = (choices or {}).get("discarded_for_cost") or ()
        if len(cost_discards) == 1:
            permanent.metadata[CAST_COST_DISCARD_MANA_VALUE] = int(
                getattr(cost_discards[0], "cmc", 0) or 0
            )
        # "…the controller of **the permanent it becomes** sacrifices it at
        # the beginning of the next cleanup step" (Mirage's flash Auras).
        # The answer was frozen as the spell was announced, because that is
        # the only moment CR 601.3d's timing can be read; carried onto the
        # permanent here because the permanent is what the sentence acts on
        # and the stack item is gone by the time the cleanup step looks.
        # Through the one writer of a delayed mark, which records the
        # delayed ability's controller and source: CR 603.7g's — the
        # caster, and the card whose static ability let it be cast as
        # though it had flash. Nothing is resolving in
        # ``resolving_seats`` here to ask, so the caster is said.
        if (choices or {}).get(CAST_AT_INSTANT_SPEED):
            mark_delayed_destruction(
                self, permanent, CAST_AT_INSTANT_SPEED, cause=caster_index,
            )
        # "As an additional cost to cast this spell, choose a creature
        # type." (Caller of the Hunt.) The word was chosen at CR 601.2b and
        # rode the stack item; it is copied onto the permanent here because
        # the permanent is what the card's other line reads it off
        # ("creatures of the chosen type"), through the same
        # ``chosen_creature_type`` metadata key An-Zerrin Ruins' *entry*
        # choice writes — one key, so `subject_filters` has one reader
        # whichever step of CR 601 or CR 614 made the choice.
        #
        # Stamped **before** the permanent enters, which is the whole of
        # what makes this a cast-time cost rather than an entry effect: the
        # characteristic-defining P/T is computed from the moment the
        # permanent is on the battlefield (CR 604.3, CR 613.1), and a
        # creature that arrived without its word would be a 0/0 that
        # CR 704.5f bins before anyone could answer a prompt. It is also
        # why a Caller of the Hunt put onto the battlefield *without being
        # cast* is that 0/0 — correctly: no cast, no CR 601.2b, no type.
        chosen_creature_type = (choices or {}).get("chosen_creature_type")
        if chosen_creature_type:
            permanent.metadata["chosen_creature_type"] = chosen_creature_type
        # CR 108.3: a permanent spell cast out of another seat's zone
        # (Grinning Totem) enters under its caster's control and is still
        # its owner's card. ``owner_index_of`` otherwise answers with the
        # seat it entered under, so it would die into the caster's
        # graveyard (CR 400.3). The channel reanimation and Desertion
        # already write for the same reason; stamped before the entry so an
        # entry replacement that sends it "to its owner's graveyard instead"
        # reads the right owner too.
        if owner_seat != caster_index:
            permanent.metadata["owner_player_index"] = owner_seat
        # What watches a land **play** (CR 116.2a's special action), as
        # against its entry: Fastbond's rider, "whenever a player plays a
        # land" (Horn of Greed), "when you play a card" (Juju Bubble).
        # ``arrived`` runs it whether the entry happened or a replacement
        # took it away — see the branch there for why.
        def announce_land_play() -> None:
            if self.enforce_mana_costs:
                if self.lands_played_this_turn.get(caster_index, 0) > 1:
                    # "…if it wasn't the first land you played this turn,
                    # ~ deals N damage to you". The rider is read off each
                    # source's own text alongside the allowance it came
                    # with, so the sources name themselves in the log
                    # instead of the engine naming one of them.
                    sources = [
                        (source, allowance)
                        for source, allowance in self._land_play_allowances(caster_index)
                        if allowance.damage_per_extra_land
                    ]
                    if sources:
                        total = sum(a.damage_per_extra_land for _, a in sources)
                        names = ", ".join(
                            dict.fromkeys(source.card.name for source, _ in sources)
                        )
                        # Asks CR 616.1e's question (``asks``). The
                        # rider is a triggered ability by its own text,
                        # resolved here rather than on the stack, so
                        # what this land play does next — the "plays a
                        # land" announcement — happening before the
                        # answer is the order the rules would give that
                        # trigger anyway.
                        self._deal_damage_to_player(
                            caster, total, asks=True,
                            then=lambda damage: self.log.append(
                                f"{names} dealt {damage} damage to {caster.name}"
                            ),
                        )
            # "Whenever an opponent **plays** a land" (Dirtcowl Wurm).
            # CR 305.1's special action, announced here because here is
            # where it happens — "whenever a land enters" (Ankh of
            # Mishra) is the *entry*, which a land put onto the
            # battlefield by an effect also makes and this one does
            # not, and is announced with every entry
            # (``ZoneFunnelsMixin._announce_entry``).
            #
            # ``event_subject_player`` beside ``seat``: the first is the
            # one key every reader of a printed "**that player**" asks for
            # (CR 603.10) and the second is what this event's own filter
            # compares against the observer. Horn of Greed's "that player
            # draws a card" is a different seat on every land drop, and
            # nothing on a board records who played one — so the freeze has
            # to happen here, where it is known.
            # ``played_permanent_id`` is what "**another** land" (City of
            # Traitors) is compared against. A land whose entry happened
            # is on the battlefield and observing by the time this is
            # announced, so a land whose own trigger watches land drops
            # would see itself — and the exclusion cannot be answered from
            # ``card``, because a deck repeats one immutable
            # ``CardDefinition`` per copy and a second printing of the same
            # land would read as the first. CR 400.7's id is the identity,
            # stamped as the permanent is built, so a play whose entry was
            # replaced carries one too.
            emit(
                self, "land_played", subject=card, seat=caster_index,
                event_subject_player=caster_index,
                played_permanent_id=permanent.permanent_id,
            )
            # "When **you play a card**" (Juju Bubble). CR 701.18b's other
            # half: a land is played rather than cast, so the cast
            # announcement never reaches it. Outside the cost-enforcement
            # branch the drop count below sits in, because a land played
            # in a game with costs off is still a land played.
            emit(self, "you_play_card", subject=card, caster_index=caster_index)

        # Everything below is what watches a permanent *enter* — the log
        # line, the global buff, its own entry trigger, the Aura's attach,
        # a land play's announcement — so it is the entry's ``then``: run
        # once the permanent is on the battlefield, which is at once unless
        # an "as it enters" choice is owed at a table that holds for the
        # answer (CR 614.12a, ``engine/entry_awaiting.py``), and then at
        # the last answer.
        def arrived() -> None:
            # CR 614: an entry replacement may have consumed the event, and then
            # the permanent is on no battlefield at all - Frankenstein's Monster
            # cast for an X its graveyard cannot pay goes to its owner's
            # graveyard "instead of onto the battlefield".
            #
            # Everything below this line is something that watches a permanent
            # *enter*: the log line, the global buff, the enters-the-battlefield
            # trigger, the Aura's attach. Running any of them for an entry that
            # did not happen is the "when it enters, do X instead" reading that
            # engine/replacements/ exists to avoid, one layer up from the
            # interceptor - and the log line saying the permanent was put onto
            # the battlefield is the same claim in the one place a player reads.
            #
            # **Whether the entry happened, not whether the permanent is
            # still there** (``entry_happened``): a land Land Equilibrium's
            # "then sacrifices a land" took straight back out entered, and
            # a seat nobody asks has sacrificed it before this runs. Read
            # as "it never entered", its play went unannounced and its log
            # line unwritten.
            if not entry_happened(permanent):
                if primary_type == "land":
                    # **A land play whose entry was replaced was still
                    # played.** A Lake of the Dead whose Swamp nobody can
                    # sacrifice goes to the graveyard instead of entering
                    # (CR 614.6), and what the replacement changed is
                    # where the land went, not whether its player took
                    # CR 116.2a's special action: "a modified event occurs
                    # instead, which may in turn trigger abilities", and
                    # the modified event is still the play — as a discard
                    # madness exiles is still a discard (CR 702.35a). It is
                    # the same play CR 305.2a counted as one of "the lands
                    # they have already played this turn" below, which is
                    # the verb Horn of Greed and Fastbond print. Reading
                    # CR 603.2g as "no entry, no play" would also make a
                    # Lotus Vale whose toll was paid — an entry replaced by
                    # "sacrifice … If you do, put it onto the battlefield",
                    # a put, CR 305.4 — never played at all.
                    #
                    # The entry's own watchers ("whenever a land enters",
                    # Ankh of Mishra) are the entry's, and stay unasked.
                    announce_land_play()
                return
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            is_aura = "Aura" in card.type_line
            if not is_aura and copy_on_enter_type(
                compile_card_oracle(text_card).normalized_text or ""
            ) is not None:
                # **The cast's target was the object to copy.** A permanent
                # that offers a copy choice as it enters (Clone, Vesuvan
                # Doppelganger, Copy Artifact — CR 707.5's "as a copy", a
                # CR 614.1c replacement) announces *that* at cast:
                # ``cast_targets._cast_target_spec`` raises the copy picker in
                # place of an entry trigger's. So whatever entry trigger the
                # copied object brings (CR 707.5) was announced by nobody, and
                # handing it the cast's target would aim it at the creature
                # that was copied — a Clone of Man-o'-War bouncing the
                # Man-o'-War. It chooses its own as it is put on the stack
                # (CR 603.3d), exactly as the same trigger does on an entry
                # nothing cast.
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, None, None, None,
                    targets_announced=False,
                )
            elif not is_aura:
                # ...and a cast that announced **nothing** — a headless or
                # scripted cast with no picker in front of it — is the same
                # "nobody chose" as an entry nothing cast. Handed in as if it
                # were an announcement, the inline path fell back to scanning
                # the *caster's* board: a bare Nekrataal destroyed its
                # caster's Savannah Lions and a bare Ravenous Rats made its
                # caster discard.
                announced = any(
                    value is not None
                    for value in (
                        target_player_index, target_permanent_index,
                        target_permanent_id, stack_target,
                        target_graveyard_card,
                    )
                )
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                    targets_announced=announced,
                    # …and the card in a graveyard the cast named for it,
                    # by the stamp the spell's push took (the stamp is the
                    # target; there is no slot to hand over).
                    target_graveyard_card=target_graveyard_card,
                    # "When this creature enters, counter target spell" (Mystic
                    # Snake): the spell the cast named. It was dropped here, so
                    # the trigger named nothing and countered the top of the
                    # stack whichever spell the caster had picked.
                    target_stack_item=stack_target,
                )
            ran_entry_text = self._apply_aura_effect(
                caster_index,
                permanent,
                target_player_index,
                target_permanent_index,
                target_permanent_id,
                target_graveyard_card=target_graveyard_card,
            )
            # An Aura's own "when this Aura enters" trigger, for every Aura whose
            # entry text `_apply_aura_effect` did *not* perform itself.
            #
            # This used to be skipped for all of them, on the strength of the two
            # it does perform bespokely (Animate Dead's reanimation, Earthbind's
            # conditional damage) — so an Aura whose entry trigger compiled to an
            # ordinary instruction did nothing at all while reporting supported.
            # Three cards were in that state.
            #
            # After the attach rather than before it, which is the order the rest
            # of the engine already keeps: "when this Aura enters, tap enchanted
            # creature" has nothing to tap until the Aura is attached.
            if is_aura and not ran_entry_text:
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                )
            # An Aura that failed to attach (its target left the battlefield while the
            # spell was on the stack) goes to its owner's graveyard instead of
            # remaining on the battlefield unattached (MTG Rule 303.4g)
            if (
                "Aura" in card.type_line
                and aura_enchant_clause(text_card.oracle_text) is not None
                and permanent.metadata.get("attached_to") is None
                and self.is_on_battlefield(permanent)
            ):
                holder = self.controller_index_of(permanent)
                if holder is not None:
                    self.remove_from_battlefield(permanent)
                self.put_card_into_graveyard(owner, card)
                self.log.append(f"{card.name} had no legal target and was put into {owner.name}'s graveyard")
                self._refresh_dynamic_creatures()
                return
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                announce_land_play()
        if primary_type == "land" and self.enforce_mana_costs:
            # **The land drop is spent by the play, whatever its entry
            # does** (CR 305.2a counts "the number of lands they have
            # already played this turn"; CR 116.2a: playing a land is a
            # special action a player takes once). So it is counted here,
            # as the action is taken, and not by ``arrived`` — which runs
            # only for an entry that happened: a Lake of the Dead whose
            # Swamp nobody could sacrifice goes to its owner's graveyard
            # instead of entering (CR 614.6), and the play that sent it
            # there was still the turn's land play. Counted it was not, and
            # a Forest could follow it.
            #
            # What watches the *play* — "whenever a player plays a land"
            # (Horn of Greed), Fastbond's "if it wasn't the first land" —
            # is announced from ``arrived`` for the same play, entered or
            # replaced (``announce_land_play``), after the entry has done
            # what it does; Fastbond's rider reads this count.
            self.lands_played_this_turn[caster_index] = (
                self.lands_played_this_turn.get(caster_index, 0) + 1
            )
        self._put_permanent_onto_battlefield(
            caster_index, permanent, target_player_index,
            was_cast=True, from_zone=cast_from_zone,
            # …and a land that came down this road was played, not cast
            # (CR 305.1) — the same road, so the same flag, and this one
            # beside it for the two readers that mean a *spell*.
            played_as_land=primary_type == "land",
            then=arrived,
        )
        if self.entry_is_awaited(permanent):
            # CR 608.2: the spell is still resolving while its permanent's
            # entry choice is owed — the line a held spell writes, so the
            # log does not go quiet where the player is being asked.
            held = self.resolving_stack_item
            if held is not None and held.card is card:
                self._log_spell_awaiting_choice(card)
        return
