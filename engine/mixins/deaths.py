"""A permanent put into a graveyard from the battlefield - CR 700.4's "dies" - and the triggers that watch it.

``_permanent_to_graveyard`` is the move, whatever made it: a would-die
replacement (CR 614) and a wider "would leave the battlefield" one are asked
first, a token ceases to exist (CR 704.5d), and the card goes to its
*owner's* graveyard through the graveyard funnel. Its two named roads are
here as well: ``sacrifice_permanent`` / ``sacrifice_permanents`` (CR
701.21a; sacrificing is not destroying, so no regeneration), and
``_destroy_swept_permanents``, the destroy sweep, which announces a
destruction (``engine/destruction_events.py``) only when its caller says the
move is one (CR 701.8b) - ``EffectsMixin._destroy_target_permanent`` is the
other destroy seam.

``_fire_permanent_dies_triggers`` and ``_fire_creature_dies_triggers`` put
the "whenever ... is put into a graveyard from the battlefield" triggers on
the stack, each with its last-known-information context. A few are
carried out inline instead, each for the reason its own block gives, and are
named in ``_INLINE_DIES_KINDS`` so the general enqueue beside them is
"everything else".
"""

from __future__ import annotations

import re

from ..card_hooks import ON_LEAVE_BATTLEFIELD
from ..auras import auras_attached_to
from ..destruction_events import (RESOLVING, announce_destroyed,
                                  destruction_finished)
from ..delayed_triggers import fire_delayed_triggers
from ..events import emit
from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..replacements import apply_replacements
from ..regeneration import regeneration_replaces_destruction
from ..trigger_utils import make_trigger_event, matching_triggers


# The dies-triggers ``_permanent_to_graveyard`` carries out **inline** rather
# than putting on the stack, each for the reason its own block there gives: the
# life loss is part of the state-based sweep, the token is an obligation the
# source outlives, and the combat relationship is unreadable a line later. They
# are named here rather than tested for one at a time, so the general enqueue
# beside them is "everything else" — a set that can be read, instead of a
# sequence of loops whose gaps only show up as a card doing nothing.
#: The two death conditions keyed on **who dealt the damage** rather than on
#: whose death it was: "a creature dealt damage by *this* creature this turn
#: dies" (Sengir Vampire, Axelrod Gunnarson) and the same sentence read off an
#: attachment (Vampiric Embrace). One scan answers both, because the only thing
#: that differs is which permanent the condition calls the killer -- and two
#: scans is the shape this file's other comments keep naming, one fire site per
#: card and every later card forgotten.
_DAMAGER_DEATH_CONDITIONS = frozenset({
    "creature_dealt_damage_by_self_dies",
    "creature_dealt_damage_by_attached_dies",
})


_INLINE_DIES_KINDS = frozenset({
    "owner_loses_half_life",                    # Personal Incarnation
    "destroy_creatures_in_combat_with_source",  # Abu Ja'far
})


class DeathsMixin:
    def _permanent_to_graveyard(self, player: PlayerState, permanent: Permanent) -> None:
        """Move a permanent to the graveyard. Tokens (704.5d) cease to exist instead.

        Recorded on ``Game.departing`` for the duration: the dies-triggers this
        announces go on the stack — and a non-interactive seat's picker takes
        its default target — while *permanent* is still listed on its
        battlefield, and ``StackItem.targets_chosen`` has to know that such a
        default was not a choice off the board the trigger will resolve on.
        """
        self.departing.append(permanent)
        try:
            self._move_permanent_to_graveyard(player, permanent)
        finally:
            self.departing.pop()

    def _move_permanent_to_graveyard(self, player: PlayerState, permanent: Permanent) -> None:
        """:meth:`_permanent_to_graveyard`'s body."""
        if "Aura" in permanent.card.type_line:
            self._remove_aura_effects(permanent)
        # CR 614 would-die replacements (Disintegrate's "exile it instead"):
        # a consumed event never reaches the graveyard, so no dies-triggers fire.
        consumed, _ = apply_replacements(
            self, "would_die", {"player": player, "permanent": permanent}
        )
        if consumed:
            return
        # …and the wider event the graveyard is one destination of: "if the
        # creature **would leave the battlefield**, exile it instead" (Dreams of
        # the Dead). A second contention set at the same moment rather than a
        # widening of the one above, because the two are different printed
        # effects — a death is one of four ways a permanent leaves — and no card
        # in the pool carries both. Asked after it for the same reason it is
        # asked at all: the narrower reading is the one a card printed about
        # dying means.
        if self._leaving_battlefield_replaced(permanent, player, "graveyard"):
            return
        if not permanent.metadata.get("is_token", False):
            # CR 400.3: the card goes to its owner's graveyard, which differs
            # from the controller's when the permanent was stolen (Control Magic).
            owner_idx = self.owner_index_of(permanent)
            owner = self.players[owner_idx] if owner_idx is not None else player
            # Through the one graveyard seam, so "if a card would be put into
            # your graveyard from anywhere" sees a death like every other move.
            # A diverted card means **nothing died** (CR 700.4: dying is being
            # put into a graveyard from the battlefield), so the dies-triggers
            # and the death tallies below are skipped — the same early return
            # the `would_die` replacement above already takes, one rule further
            # down. The token branch is deliberately outside this: CR 111.7
            # keeps a token's card out of the pile while leaving it something
            # that died.
            if not self.put_card_into_graveyard(
                owner, permanent.card, from_zone="battlefield",
                from_battlefield=permanent,
            ):
                return
        # "Whenever a land is put into a graveyard from the battlefield…"
        # (Dingus Egg). Announced here, on the one seam every land death
        # already passes through, not from the destruction paths: it used to be
        # a call inside `_destroy_target_permanent` plus a second inside a
        # card hook, so a land destroyed by the several-targets branch
        # (Avalanche), a board sweep (Armageddon) or a sacrifice fired nothing
        # — the `become_tapped` shape, one fire site per path and every new
        # path forgotten. Asked through `has_type` (CR 613 layer 4), the same
        # reading `is_creature` below takes for the same reason: an animated
        # or type-changed land is still a land when it dies.
        if permanent.has_type("land"):
            self._process_land_dies(self.players.index(player))
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
            # "…for each creature put into **your graveyard** from the
            # battlefield this turn" (Asmira, Holy Avenger). CR 400.3's seat,
            # not CR 109.5's: the card goes to its *owner's* graveyard, which is
            # a different player from the one above whenever the permanent was
            # stolen. Counted for a token too — CR 111.7 puts it into the
            # graveyard and only then does the state-based action make it cease
            # to exist, so the sentence is true of it even though nothing is
            # there to find afterwards, which is why this is a tally and not a
            # read of the pile.
            owner_seat = self.owner_index_of(permanent)
            grave_owner = (
                self.players[owner_seat] if owner_seat is not None else player
            )
            grave_owner.creatures_put_into_your_graveyard_this_turn += 1
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
        # CR 700.4's death of **any** permanent, not only a creature's. The
        # loop sat inside the `is_creature` branch above, so an Aura, an
        # artifact or an enchantment printing its own death trigger compiled
        # one and nothing ever enqueued it — the shape `_INLINE_DIES_KINDS`
        # names one screen up, one gate further out. Lich is the card that
        # paid for it: its whole downside was carried by a **text match on
        # the printed sentence**, inline and off the stack, because the
        # general path could not reach a non-creature. That branch is gone
        # with this lift, for the reason Creature Bond's bespoke dispatcher
        # went (`grammar/lowering/_bound_returns.py`): one event announced
        # by two mechanisms fires twice on the paths both reach.
        #
        # Still inside `_permanent_to_graveyard`, which is what makes it a
        # claim about *this* permanent's death: the board-wide scan is
        # `_fire_permanent_dies_triggers` below, and a permanent is reached
        # by exactly one of the two.
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
        # ``dead_power`` and ``dead_toughness`` are captured for every
        # trigger whether or not it asks: the permanent is about to leave
        # and CR 603.10 says the trigger uses the information the game had,
        # so the read has to be here even though only some payloads consume
        # it. Both characteristics, for the same reason there is one read
        # rather than one per card — a fire site that freezes only what
        # today's cards ask for is a fire site the next card has to edit.
        # ``enters_or_dies`` beside ``dies``: "When this creature **enters or
        # dies**, create two 1/1 red Goblin creature tokens." (Goblin Marshal,
        # Hunting Moa.) CR 603.1's one ability with two trigger events, and the
        # engine's answer to that shape is one condition kind named at both fire
        # sites — the arrangement ``creature_attacks_or_blocks`` has in the two
        # declaration steps, and ``phases_out_or_leaves_battlefield`` has beside
        # its own announcement.
        #
        # Named **here** rather than aliased into ``dies`` at the compiler,
        # because the two halves are announced from different fire sites: the
        # entry half by
        # ``stack/resolution._apply_self_enters_battlefield_triggers`` and this
        # half here, each onto the stack (CR 603.3). A single kind that meant
        # "dies" to the compiler would have no entry half at all.
        for trig in matching_triggers(
            permanent.effective_card, condition_kinds={"dies", "enters_or_dies"},
        ):
            if trig.instruction is None or trig.instruction.kind in _INLINE_DIES_KINDS:
                continue
            # "When this creature dies **during combat**" (Mongrel Pack).
            # CR 506.1's phase, asked of the death: the same death outside
            # combat is a different card. Enforced here rather than
            # dropped, for the reason every narrowing in this engine is —
            # an unenforced restriction is an ability that works *more*
            # often than the card allows, wrong in the player's favour and
            # silent. An absent key is the unnarrowed printing.
            if (
                trig.condition.payload.get("dies_during_combat") is not None
                and self.current_turn_phase != "combat"
            ):
                continue
            self._enqueue_triggered_ability(
                controller_index=self.players.index(player),
                source_permanent=permanent,
                card=permanent.card,
                instruction=trig.instruction,
                effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
                trigger_context={
                    "dead_power": max(0, permanent.effective_power),
                    "dead_toughness": max(0, permanent.effective_toughness),
                    # The counters it carried, frozen for the paragraph
                    # above's reason and spelled the way the *other* death
                    # fire site spells them: "when a creature dies" and
                    # "when **this** creature dies" are two loops over one
                    # event, and last-known information that only one of
                    # them records is a condition that answers differently
                    # depending on which loop announced it.
                    #
                    # "…exile it **if it had a death counter on it**"
                    # (Bogardan Phoenix) is the card that needs the second
                    # of these, and it needs it here: its own death is what
                    # fires it, and its counters are gone the instant the
                    # card reaches the graveyard (CR 400.7).
                    "had_plus1_counter": (
                        int(permanent.metadata.get("plus_counters", 0)) > 0
                    ),
                    "dead_counters": {
                        key[: -len("_counters")]: int(value or 0)
                        for key, value in permanent.metadata.items()
                        if isinstance(key, str) and key.endswith("_counters")
                    },
                },
            )
            self.log.append(f"{permanent.card.name} triggered (died)")
        # Lich's "you lose the game" was here, as a **substring test on the
        # printed sentence**, applied inline and off the stack. It existed
        # because the general dies-enqueue above could not reach a non-creature
        # permanent, not because the rule is special: CR 603.3 puts a death
        # trigger on the stack whatever the permanent's type, and the loop
        # above now does. Keeping both would fire the loss twice on every path
        # that reaches both, which is Creature Bond's bug in a different zone.

        if permanent.card.primary_type == "creature":
            # "…if a creature dealt damage by this creature this turn **died**"
            # (Krovikan Vampire). The ledger the intervening-if reads, written
            # here rather than at the fire site below it: this is the one place
            # a death and its damagers are both in hand, and the question is
            # asked a whole end step later, when the permanent is gone and its
            # `damaged_by_sources_this_turn` record has gone with it.
            #
            # On each damager, by identity, holding the *card* — which is what
            # "that card" names and the only part of a dead creature that
            # survives (CR 400.7). A damager that itself leaves takes its ledger
            # with it, which is correct: the permanent that comes back is a new
            # object and never dealt that damage.
            for damager in permanent.metadata.get(
                "damaged_by_sources_this_turn", []
            ):
                damager.metadata.setdefault(
                    "damaged_creatures_that_died_this_turn", []
                ).append(permanent.card)
            # The seat this move is being made for, handed down because the
            # layer-2 read below cannot always answer: the destruction paths
            # disagree about whether the permanent is removed from the
            # battlefield before or after this call, and once it is off there is
            # no battlefield to read a controller from. CR 603.10 wants the
            # last-known one either way. `player` is what the two blocks above
            # already treat as the controller (the loses-the-game check, and the
            # `controller_index` every dies-trigger is enqueued under).
            self._fire_creature_dies_triggers(
                permanent, self.players.index(player)
            )
        self._fire_permanent_dies_triggers(
            permanent, self.players.index(player)
        )
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

        # The *effective* name (CR 707.2): the hook implements what the
        # permanent's text said, and a copy carries the copied text — a Clone
        # of Gaea's Liege forested lands through that text, so its leaving is
        # what reverts them. The printed face here left every copy's linked
        # effect standing.
        leave_hook = ON_LEAVE_BATTLEFIELD.get(permanent.effective_card.name)
        if leave_hook is not None:
            leave_hook(self, player, permanent)

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
        return min(candidates, key=DeathsMixin.sacrifice_preference_key)

    @staticmethod
    def sacrifice_preference_key(permanent: Permanent):
        """The order a seat gives permanents up in — lowest first.

        Split out of :meth:`default_sacrifice_pick` because a caller that has to
        pay **several** costs at once cannot pick them one at a time: CR 508.1h's
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

    def sacrifice_permanents(self, permanents) -> list[Permanent]:
        """Sacrifice several permanents **at once** — CR 701.21a for a set
        that leaves in one event ("…then sacrifices the rest", Cataclysm).

        Not a loop over :meth:`sacrifice_permanent`, for the reason
        :meth:`_destroy_swept_permanents` is not a loop over a destroy: an
        ability that triggers on a permanent leaving looks back in time
        (CR 603.10a), so a watcher going in the same event still sees the
        others go. One at a time, a Dingus Egg sacrificed ahead of the lands
        beside it saw none of them — and none of the other player's, whose
        sacrifices are the same event by the card's own ruling.

        So it has that sweep's shape: every permanent reaches its graveyard
        **while all of them are still listed**, then they come off their
        battlefields together, then each sacrifice is announced. Sacrificing is
        not destroying (701.21a), so nothing regenerates and nothing is
        indestructible here. A permanent nobody controls any more is skipped,
        and one named twice is sacrificed once.

        Returns those sacrificed, in the order they were named.
        """
        doomed: list[tuple[Permanent, int]] = []
        for permanent in permanents:
            seat = self.controller_index_of(permanent)
            if seat is None or any(permanent is listed for listed, _ in doomed):
                continue
            doomed.append((permanent, seat))
        for permanent, seat in doomed:
            # Before the graveyard move, which is what announces the death —
            # see :meth:`sacrifice_permanent`.
            permanent.metadata["was_sacrificed"] = True
            self._permanent_to_graveyard(self.players[seat], permanent)
        self.remove_all_from_battlefield([permanent for permanent, _ in doomed])
        for permanent, seat in doomed:
            emit(self, "you_sacrifice_permanent", subject=permanent, seat=seat)
        return [permanent for permanent, _ in doomed]

    def _destroy_swept_permanents(
        self,
        player: PlayerState,
        matches,
        *,
        allow_regeneration: bool = True,
        respect_indestructible: bool = True,
        on_regenerate=None,
        on_destroy=None,
        cause=RESOLVING,
    ) -> list[Permanent]:
        """Destroy every permanent on *player*'s battlefield that ``matches``.

        **The caller says whether this is a destruction, and whose** (*cause*).
        This sweep is the road to the graveyard for more than CR 701.8's
        action: a creature with toughness 0 (CR 704.5f), a planeswalker with no
        loyalty (704.5i), an Aura attached to nothing (704.5m) and two
        sacrifices all leave through it, and CR 701.8b is exact that none of
        those "has been destroyed". So a caller making one of those moves
        passes ``NOT_A_DESTRUCTION`` and nothing is announced; the lethal-damage
        sweep passes ``NO_SPELL_OR_ABILITY`` (destroyed, and by no spell or
        ability — said rather than read off whatever is resolving, because
        state-based actions are checked inside resolutions too); a delayed
        destruction passes the seat that set it up (CR 603.7d–e). The default
        is CR 109.5's controller of whatever is resolving, which is every
        effect handler's answer. *cause* may also be a callable taking the
        permanent, for the delayed sweeps, whose victims were marked by
        different players' effects. See ``engine/destruction_events.py``.

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
            # Destroyed (CR 701.8a) — announced while it is still listed, as
            # the single-permanent seam announces it and for its reasons
            # (CR 603.10a; a replaced move is still a destruction).
            announce_destroyed(
                self, permanent, cause(permanent) if callable(cause) else cause
            )
            self._permanent_to_graveyard(player, permanent)
            if on_destroy is not None:
                on_destroy(permanent)
            destroyed.append(permanent)
        self.remove_all_from_battlefield(destroyed)
        destruction_finished(self)
        return destroyed

    def _fire_permanent_dies_triggers(
        self, dead_permanent: Permanent, last_known_seat: int | None = None
    ) -> None:
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

        # Who controlled it, for "**its controller** discards a card"
        # (Bereavement). CR 603.10's last known information: by the time the
        # trigger resolves the permanent is a card in a graveyard, which
        # CR 108.4 gives no controller at all — and under a control-change
        # effect that seat was never its owner either, so neither the card nor
        # the ownership can answer.
        #
        # Read off the battlefield first and falling back to the seat the
        # caller is making this move for, exactly as `_fire_creature_dies_
        # triggers` does one screen down and for its reason: the destruction
        # paths disagree about whether the permanent is removed before or after
        # this call, so on half of them there is no battlefield left to read.
        dead_seat = self.controller_index_of(dead_permanent)
        if dead_seat is None:
            dead_seat = last_known_seat
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
                grave_owner = trig.condition.payload.get("dying_graveyard_owner")
                if grave_owner is not None:
                    owner_index = self.owner_index_of(dead_permanent)
                    # "an opponent's" is the mirror of "your" and not a second
                    # question: CR 102.2 makes an opponent every player who is
                    # not you, so both readings are one comparison against the
                    # observer's seat read the two ways round. A card printing
                    # neither leaves the key absent and every graveyard counts.
                    mine = owner_index == controller_index
                    if mine is not (grave_owner == "your"):
                        continue
                # "…**a spell or ability an opponent controls causes** a land
                # to be put into your graveyard" (Sacred Ground). Who caused
                # the death, which nothing on a board records once it has
                # happened: `resolving_seats` is CR 109.5's controller of
                # whatever is resolving, the same answer the discard seam gives
                # Psychic Purge's identical question one action over. An empty
                # stack means no spell or ability caused it — a state-based
                # action, a cost, a turn-based effect — which is exactly when
                # this trigger must not fire.
                if trig.condition.payload.get("dying_cause") == "an opponent":
                    causer = (
                        self.resolving_seats[-1] if self.resolving_seats else None
                    )
                    if not isinstance(causer, int) or causer == controller_index:
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
                        # "…you gain life equal to **its toughness**" (Grim
                        # Feast). Last known information (CR 603.10 / 608.2h):
                        # the number the permanent had on the battlefield, so a
                        # creature that died pumped or shrunk is worth what it
                        # was worth. By resolution it is a card in a graveyard
                        # with a printed number and no anthem on it, which is
                        # the wrong answer and an invisible one. Frozen for
                        # every trigger whether or not it asks, exactly as the
                        # creature-death site freezes them.
                        "dead_power": max(0, dead_permanent.effective_power),
                        "dead_toughness": max(0, dead_permanent.effective_toughness),
                        # The seat above, under the one key every event that is
                        # *about an object* records its subject's controller
                        # under — so "its controller" means the same thing here
                        # as it does on a tap, a block or a damage event, and
                        # `_EVENT_SUBJECT_CONTROLLERS` can name this condition
                        # without a second reader.
                        "event_subject_controller": dead_seat,
                        # "…create a 1/1 green Saproling creature token **for
                        # each fungus counter on that creature**"
                        # (Sporogenesis). The counters with no rules meaning of
                        # their own (CR 122.3), frozen for the same reason the
                        # two numbers above are and spelled the way both sibling
                        # death sites already spell them.
                        #
                        # This was the *third* site and the one that did not
                        # record them, which is exactly the shape
                        # ``lowering/_deaths.py`` calls a claim about a fire
                        # site: Sporogenesis' condition is ``permanent_dies``
                        # and so is announced from here alone, so the clause
                        # parsed, lowered and resolved to **zero** tokens with
                        # every guard green.
                        "dead_counters": {
                            key[: -len("_counters")]: int(value or 0)
                            for key, value in dead_permanent.metadata.items()
                            if isinstance(key, str) and key.endswith("_counters")
                        },
                    },
                ))
        self._enqueue_triggered_batch(events)

    def _fire_creature_dies_triggers(
        self, dead_permanent: Permanent, last_known_seat: int | None = None
    ) -> None:
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
        if dead_seat is None:
            # Already off the battlefield — which is the *ordinary* case on
            # half the destruction paths, not an edge one. The seat the caller
            # is making this move for is the last-known controller (CR 603.10),
            # and without it every controller-scoped death condition silently
            # went unannounced: the `if dead_seat is not None` guard below
            # skipped Massacre Wurm's whole branch, and Earthlink's "that
            # creature's controller" resolved against a frozen key holding None.
            dead_seat = last_known_seat
        died_context = {
            "dead_name": dead_permanent.card.name,
            # The card itself, for "return **that card** to its owner's hand"
            # (Puppet Master). The *name* above cannot answer: a graveyard is a
            # list of `CardDefinition`, two copies of a card are the same
            # immutable object, and a name match would find whichever entry came
            # first. The identity is what locates the one that just died.
            "dead_card": dead_permanent.card,
            # "…loses life equal to **its power** and you gain life equal to
            # **its toughness**" (Death Watch). Last known information
            # (CR 603.10 / 608.2h): the numbers the creature had on the
            # battlefield, so one that died pumped or shrunk is worth what it
            # was worth. By resolution it is a card in a graveyard with a
            # printed number and no anthem on it, which is the wrong answer and
            # an invisible one.
            #
            # Frozen for **every** trigger this site announces whether or not it
            # asks, exactly as the two sibling death sites do. The comment
            # beside the permanent-death site already claimed this one froze
            # them; it did not, so every condition announced from here — an
            # Aura's "when enchanted creature dies", "whenever a creature dies",
            # both controller-scoped spellings — was refused the phrase for want
            # of a key nobody wrote.
            "dead_power": max(0, dead_permanent.effective_power),
            "dead_toughness": max(0, dead_permanent.effective_toughness),
            "had_plus1_counter": int(dead_permanent.metadata.get("plus_counters", 0)) > 0,
            # "…**if it had a death counter on it**" (Bogardan Phoenix). The
            # counters with no rules meaning of their own (CR 122.3), which live
            # one metadata key per word and so cannot be frozen as the single
            # bool above. Its own key rather than that one widened — two records,
            # and a reader of one must fail by name rather than receive the
            # other. Frozen here for CR 603.10's reason: a graveyard card has no
            # counters at all, so nothing downstream could read the answer.
            "dead_counters": {
                key[: -len("_counters")]: int(value or 0)
                for key, value in dead_permanent.metadata.items()
                if isinstance(key, str) and key.endswith("_counters")
            },
            # Who controlled it, for "that player loses 2 life" (Massacre
            # Wurm): the graveyard card cannot say, and under Control Magic
            # the controller is not the owner. One key across every event that
            # is about an object — the blocker's controller Gloom Sower reads
            # is the same question asked of a different event.
            "event_subject_controller": dead_seat,
        }
        for controller_index, observer in self.permanents_with_controller():
            # The **effective** card (CR 613 layers 1, 3 and 6), like the two
            # scans just below: what the observer says now. This compiled the
            # printed card, so a Sengir Vampire under Humility went on taking
            # its counter for an ability it did not have, a Soul Net under
            # Titania's Song still offered its life — and a Clone of the
            # Vampire, which does have the ability (CR 707.2), never got one.
            program = compile_card_oracle(observer.effective_card)
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
                    trig.condition.kind in _DAMAGER_DEATH_CONDITIONS
                    and trig.instruction is not None
                ):
                    damagers = dead_permanent.metadata.get("damaged_by_sources_this_turn", [])
                    # Which permanent the condition says dealt the damage.
                    # Sengir Vampire's is the observer itself; Vampiric
                    # Embrace's is what the observer is attached to, which is
                    # the whole of the difference between the two kinds and the
                    # reason they are two. ``attached_to`` is the one record
                    # both an Aura and an Equipment write, so CR 301.5f's two
                    # words reach one answer.
                    killer = (
                        observer
                        if trig.condition.kind
                        == "creature_dealt_damage_by_self_dies"
                        else observer.metadata.get("attached_to")
                    )
                    # By identity: ``in`` compares Permanent by value, and a
                    # look-alike of the killer is not the killer (CR 400.7).
                    if killer is not None and any(
                        entry is killer for entry in damagers
                    ):
                        # The dying card travels with the trigger, exactly as
                        # the three scans above already send it. Seraph's "put
                        # **that card** onto the battlefield under your control"
                        # has nowhere else to read it — by resolution the
                        # permanent is gone and its card is in a graveyard — and
                        # this branch was the one scan of the four that dropped
                        # the context, so the lowering gate refused the sentence
                        # for an event whose fire site had simply never been
                        # asked to carry it.
                        events.append(make_trigger_event(
                            controller_index, observer, trig,
                            trigger_context=died_context,
                        ))
                    continue
                if trig.condition.kind != "creature_dies" or trig.instruction is None:
                    continue
                instr = trig.instruction
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
                    continue
                # Every other "whenever a creature dies" ability, with the
                # death's own frozen facts (CR 603.10) — the same context the
                # two scoped death conditions above are announced with.
                #
                # This branch used to be two: ``may`` and ``target_gains_life``,
                # and any other instruction kind was dropped without a word. It
                # is the narrowing the Sengir Vampire comment above rejects for
                # its own condition, made once more one branch down: what the
                # ability *does* is the effect's business, and the condition is
                # about a death. Earthlink's "that creature's controller
                # sacrifices a land" is the second card in the pool to print
                # this condition and would have been the first to be dropped.
                events.append(make_trigger_event(
                    controller_index, observer, trig,
                    trigger_context=dict(died_context),
                ))
        self._enqueue_triggered_batch(events)
