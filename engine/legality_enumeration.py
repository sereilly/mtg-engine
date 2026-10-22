"""Given a target spec, which permanents, players, graveyard cards and cards in
hand satisfy it.

What ``engine/legality.py``'s docstring calls the *enumeration*: the derivation
of a spec is ``engine/targeting.py``'s, and this is the list it is enumerated
into. :meth:`TargetEnumerationMixin._enumerate_targets` is the one list both
the target picker and every gate compare against — the cast and activation
offers, the CR 601.2c gates and the CR 608.2b re-check — which is what makes
"offered" and "accepted" one answer; :meth:`TargetEnumerationMixin._ability_target_legal`
is an activated ability's own printed narrowing asked of each candidate, and
:meth:`TargetEnumerationMixin._permanent_matches_target_kind` the target kind's.

A target on the stack is enumerated by ``engine/legality_stack.py``, which
this reaches for a ``stack`` spec.
"""

from __future__ import annotations

from .handlers._common import (
    excluded_graveyard_slot,
    graveyard_card_matches,
    permanent_matches_filter,
    state_holds,
)
from .models import CardDefinition, Permanent
from .cast_restrictions import timing_fixed_seat
from .faces import whole_card
from .player_statics import seat_has_player_keyword
from .subject_filters import card_matches_any, subject_matches
from .targeting import (
    CAST_FROM_GRAVEYARD,
    spec_is_a_cost,
    spec_offers_a_player,
)
from .legality import _STACK_TARGET_KINDS, spec_chooses_a_source


def _cast_from_graveyard_slot(spec: dict, graveyard, spell) -> int | None:
    """The slot of *graveyard* the spell being cast out of it occupies, or
    None when this spec is not such a cast's.

    ``handlers/_common.excluded_graveyard_slot``'s shape, for the other reason
    one slot of a pile is not a candidate: there the printed word "another"
    rules out an ability's own source, here CR 601.2a has already moved the
    card to the stack. A **slot** for that function's reason too — two copies
    of one card in one graveyard are one ``CardDefinition`` object, so
    excluding by identity would take both where the cast takes one. The first
    matching slot is the one the cast path itself takes
    (``_spell_source`` walks the pile from the bottom).

    The card as the zone holds it: a split card is held whole and cast as a
    half (CR 709.4), so the half is widened before it is looked for.
    """
    if not (spec or {}).get(CAST_FROM_GRAVEYARD) or spell is None:
        return None
    held = whole_card(spell)
    return next(
        (index for index, entry in enumerate(graveyard) if entry is held),
        None,
    )


def _type_line(card: CardDefinition) -> str:
    return (card.type_line or "").lower()


def _cant_be_enchanted_by_auras(perm) -> bool:
    """Aura-derived, printed on the permanent itself, or flagged; one question,
    every source."""
    from .auras import aura_restriction_active, cant_be_enchanted_by_own_text

    return (
        bool(perm.metadata.get("cant_be_enchanted_by_auras"))
        or aura_restriction_active(perm, "cant_be_enchanted_by_auras")
        or cant_be_enchanted_by_own_text(perm)
    )


class TargetEnumerationMixin:
    """Given a spec, every legal target. Composed onto ``Game`` beside
    ``LegalityMixin``."""

    def enumerate_targets_for_kind(self, caster_index: int, card: CardDefinition, kind: str, **flags) -> list[dict]:
        """Enumerate legal targets for a pre-classified target ``kind``.

        A bare enumeration over a spec the *caller* wrote, for a caller that
        has no card-level derivation to ask. It was how the web layer filled in
        a modal mode's targets, from a kind table of its own; a mode's list is
        now ``cast_target_spec(mode_index=)``, the cast gate's own, and nothing
        in ``web/`` calls this any more."""
        spec = {"kind": kind, **flags}
        return self._enumerate_targets(caster_index, card, spec, for_cast=False)

    # -- Target enumeration ------------------------------------------------
    def _enumerate_targets(
        self, caster_index: int, card: CardDefinition, spec: dict, *, for_cast: bool,
        ability_instruction=None, source_permanent=None, ability_source=None,
        triggered: bool = False,
        # CR 601.2b's answer so far, for the per-candidate probe below: it asks
        # ``_validate_cast_targets`` about one slot, and that gate re-derives
        # the spell's spec -- which for a kicked-only target (CR 702.33g) is a
        # different spec for a kicked cast than for an unkicked one. None reads
        # every arm, which is what the probe did before a card printed one.
        optional_cost_payments: dict | None = None,
        # CR 601.2b's other answer, for the same probe: the mode a modal spell
        # was announced with. ``_validate_cast_targets`` reads the chosen
        # mode's instruction for its per-kind arm, so a probe that named none
        # judged every candidate for mode *n* against mode 0's sentence — which
        # is why the web layer enumerated a mode's targets through a second
        # path (``for_cast=False``) that skipped the arms altogether.
        mode_index: int | None = None,
    ) -> list[dict]:
        kind = spec["kind"]
        if kind in ("none", "modal"):
            return []
        # "…players and permanents can't be the targets of spells or activated
        # abilities." (Peace Talks.) CR 115.1 with nothing left to choose, so
        # the answer is the empty list and every gate above already knows what
        # to do with it — the picker offers nothing, `cast_target_refusal`
        # declines the announcement (CR 601.2c) and
        # `activation_target_refusal` declines the activation (CR 602.2b) with
        # nothing paid.
        #
        # Here rather than in ``_can_be_targeted``: that predicate is asked
        # about a **permanent** and would leave the player half unenforced, and
        # it cannot tell an activated ability from a triggered one, which this
        # sentence separates. ``triggered`` is how it is told: a triggered
        # ability is neither a spell nor an activated ability, so the ban does
        # not reach it, and its announcement (CR 603.3d, through
        # ``_choose_trigger_targets``) is the one caller that says so.
        #
        # Not a nicety while the ban is up: an empty candidate list is CR
        # 603.3c's "no legal target", which takes the ability **off the stack**.
        # Read as a spell's ban, Peace Talks would have deleted every announcing
        # trigger in the game for two turns.
        #
        # A **cost** payment is not a target (CR 601.2b vs 601.2c), and the
        # spec says so — the same flag the seat loop below reads — so a
        # sacrifice cost keeps enumerating while the ban is up. Every cost flag
        # (``spec_is_a_cost``), not the three this once listed: an exile, a
        # discard or an untap paid under Peace Talks targets nothing either.
        #
        # **A spell on the stack is neither a player nor a permanent**, so the
        # ban does not reach it — which both gates in front of this list have
        # always said (``_UNBANNABLE_CAST_KINDS``, and the activation path's own
        # copy of it) and this list did not: Counterspell was castable under
        # Peace Talks and its picker offered nothing, so the engine accepted a
        # named spell that no human seat could name. The stack half of the list
        # stands, and only that half — "target spell or permanent" (the Laces,
        # Illusion, Blind Seer) is offered the spells and none of the permanents.
        if self.targeting_bans and not triggered and not spec_is_a_cost(spec):
            if spec.get("kind") in _STACK_TARGET_KINDS:
                return self._enumerate_stack_targets(
                    caster_index, card, spec,
                    source=ability_source or source_permanent,
                )
            return []
        # "…**defending player controls**" (Floral Spuzzem, Kukemssa Pirates,
        # Yare). Not relative to the seat choosing but to a combat, and which
        # combat depends on who is asking: a *trigger* names the one it fired
        # in, which may be over by the time it resolves, so the announcement
        # freezes the seat and passes it on the spec. A **spell** has no such
        # record -- it is being cast right now -- so the seat is the live
        # combat's, through the one reader that asks CR 506.2's strict
        # question. Outside combat there is no defending player at all, so the
        # card has no legal target, which is the answer rather than a fallback.
        #
        # Resolved once, here, because the phrase is read twice below: as a
        # flag on the seat loop, and inside the printed noun phrase every
        # candidate goes through.
        defending_seat = spec.get("defending_player_index")
        if defending_seat is None:
            defending_seat = self.defending_player_index_now()
        # "…**that player** controls", resolved the same way one record over.
        # A modal spell's chooser supplies the seat on the spec (CR 700.2e) and
        # a trigger's fire site froze one; a **spell** printing the phrase in
        # its own text has neither, and the only sentence its pronoun can point
        # back at is the timing clause above it — "Cast this spell only during
        # an opponent's turn. Tap target creature that player controls."
        # (Delirium). The table that owns that phrase is what answers, so the
        # picker and the timing gate cannot disagree about which player the
        # card is talking about.
        that_player_seat = spec.get("that_player_index")
        if that_player_seat is None:
            that_player_seat = timing_fixed_seat(self, caster_index, card)
        if kind == "hand_card":
            return self._enumerate_cost_hand_cards(
                caster_index, card, spec, for_cast=for_cast
            )
        if kind == "graveyard_creature":
            # *card* is the source of the spell or ability doing the choosing
            # (CR 113.7), which is what a printed "another" is measured
            # against — and for
            # the one shape that prints it (a dies-trigger returning a card
            # from the pile its own source is now in) the source card really is
            # one of the candidates.
            return self._enumerate_graveyard_creatures(
                caster_index, spec, source_card=card
            )
        if kind == "stack":
            return self._enumerate_stack_targets(
                caster_index, card, spec,
                source=ability_source or source_permanent,
            )
        if kind == "spell_or_permanent":
            # Lace recolor: legal on any permanent on the battlefield or any spell
            # on the stack. Enumerate both and concatenate. Unsubstantiate narrows
            # the permanent half to creatures via `permanent_kind`.
            perms = self._enumerate_targets(
                caster_index, card, {**spec, "kind": spec.get("permanent_kind", "permanent")},
                for_cast=for_cast, ability_instruction=ability_instruction,
                ability_source=ability_source, triggered=triggered,
                mode_index=mode_index,
            )
            return perms + self._enumerate_stack_targets(caster_index, card, spec)

        targets: list[dict] = []
        # Player faces are legal for player-targeted, "any target", and divided
        # spells — but not a divided land selection (Volcanic Eruption's Mountains).
        #
        # ``spec_offers_a_player`` is that question, and it is asked here rather
        # than spelled out because two gates ask it too: a seat named with no
        # object beside it is a *target* exactly where this loop would have
        # offered one ("…among any number of **target creatures**", Fire
        # Covenant, names no player — without the noun, a face was offered as a
        # legal target for a spell that names none).
        if spec_offers_a_player(spec):
            for seat in range(len(self.players)):
                # **A player who has left the game is not a target.** CR 800.4a
                # takes them out of the game and CR 102.2 out of everybody's
                # opponents, so "target player" and "target opponent" alike stop
                # reaching them. ``opponents_of`` has said so since free-for-all
                # arrived and this loop never asked it — a second opinion about
                # who is still playing, and the one the picker hands the client.
                # Silent at two seats, where the game is over the moment a seat
                # is lost; at three it offered a departed player as a legal
                # answer, and Oath of Ghouls' "…whose graveyard has fewer
                # creature cards" *preferred* them, because a graveyard that has
                # left the game is empty.
                if self.players[seat].lost:
                    continue
                # "**You have shroud.**" (Ivory Mask.) CR 702.18a in as many
                # words: "This permanent **or player** can't be the target of
                # spells or abilities." Asked here, in the one list both the
                # picker and the two announcement gates read, for the reason
                # the targeting-ban check above this loop gives — a seat that
                # cannot be chosen must be missing from the candidates rather
                # than refused later by a second opinion.
                #
                # Unlike that ban, this reaches a **triggered** ability too: a
                # trigger is not a spell, but CR 702.18a says "spells or
                # abilities" and a triggered ability is one (CR 113.3c). So no
                # `triggered` exemption — the difference is in the printed
                # words, not in the mechanism.
                if seat_has_player_keyword(self, seat, "shroud"):
                    continue
                # "target opponent" (Word of Command) can't be the caster's own seat.
                if spec.get("opponents_only") and seat == caster_index:
                    continue
                # "target player **who attacked this turn**" (Fire and
                # Brimstone). The record is on the seat, not on its creatures:
                # a player who attacked and then lost the attacker still
                # attacked, and reading the board would forget them.
                if (
                    spec.get("attacked_this_turn")
                    and not self.players[seat].attacked_this_turn
                ):
                    continue
                # "target opponent **previously dealt damage by it**" (Diseased
                # Vermin). The record is on the *source permanent*, not on the
                # seat — "whom has this creature hurt" — so this is the one
                # player narrowing that needs the ability's source, and with no
                # source in hand the clause admits nobody rather than everybody:
                # an unenforceable restriction offered as satisfied is the
                # silent direction (CR 601.2c).
                if spec.get("damaged_by_source"):
                    from .damage_events import seats_dealt_damage_by

                    if ability_source is None:
                        continue
                    if seat not in seats_dealt_damage_by(ability_source):
                        continue
                # "target opponent **who has more life than you do**" (the
                # Exodus Keepers), "target player **who controls more creatures
                # than they do and is their opponent**" (the Oaths). The third
                # printed seat narrowing, and the first whose answer is a
                # *count* rather than a record — which is exactly why it can be
                # enforced here at all (CR 601.2c) where the two above needed
                # a seat record and a source respectively.
                #
                # A reference the announcement never froze admits nobody rather
                # than everybody, for the reason the source check one line up
                # does: an unenforceable restriction offered as satisfied is
                # the silent direction.
                compared = spec.get("compared")
                if compared:
                    from .player_comparisons import seat_answers_comparison

                    if not seat_answers_comparison(
                        self, seat, compared,
                        caster_index=caster_index,
                        that_player_seat=that_player_seat,
                    ):
                        continue
                # "…Destroy target nonblack creature **that player** controls"
                # (Keeper of the Dead). The *fourth* seat narrowing, and the
                # only one that is not a property of the seat at all: it asks
                # whether the board behind this candidate can fill a **later
                # slot** of the same announcement (CR 601.2c — every target is
                # chosen, or the announcement is illegal). ``_activation_spec``
                # attaches the slots; this is where a board can be read, so a
                # seat with nothing to destroy is simply not offered, and the
                # picker and the gate refuse it together rather than one of them
                # offering what the other declines.
                if not all(
                    self._enumerate_targets(
                        caster_index, card, {**slot, "that_player_index": seat},
                        for_cast=False,
                        source_permanent=source_permanent,
                        ability_source=ability_source,
                    )
                    for slot in spec.get("dependent_slots") or ()
                ):
                    continue
                targets.append({"kind": "player", "seat": seat})
            if kind == "player":
                return targets

        casting_aura = "aura" in _type_line(card)
        # **A cost payment is not a target** (CR 601.2b vs 601.2c), so none of
        # the targeting legality below applies to it: protection, shroud and
        # hexproof stop a permanent being *targeted*, and a player may always
        # sacrifice their own. The payment paths have always known this — a
        # White Knight (protection from black) is a legal payment for Sacrifice
        # and the engine takes it happily — while this enumerator refused to
        # offer one, so the answer depended on whether you were a person or a
        # script. That is the picker/resolution disagreement the round-48 guard
        # exists for, arriving through the cost field instead of the target one.
        # A tap cost and a return cost the same: tapping a White Knight to pay
        # Opposition's cost is not targeting it — and every other cost flag
        # (``spec_is_a_cost``): untapping an opponent's shrouded land to pay
        # Benthic Explorers' cost targets it no more than tapping one would.
        paying_a_cost = spec_is_a_cost(spec)
        # …and neither is a chosen **source** (CR 609.7a), for the same reason
        # one layer over: see :func:`spec_chooses_a_source` and the gate below.
        choosing_a_source = spec_chooses_a_source(spec)
        for seat, player in enumerate(self.players):
            # A sacrifice cost (Sacrifice) only offers the caster's own creatures.
            if spec.get("own_only") and seat != caster_index:
                continue
            # "…an opponent controls" — the activator's own permanents are not
            # legal answers. The same seat test as `own_only` one line up, in
            # the other direction.
            if spec.get("opponent_only") and seat == caster_index:
                continue
            # "…**defending player controls**" (Floral Spuzzem, Yare). Not
            # relative to the seat choosing but to a combat, and which combat
            # depends on who is asking: a *trigger* names the one it fired in,
            # which may be over by the time it resolves, so the announcement
            # freezes the seat and passes it on the spec. A **spell** has no
            # such record — it is being cast right now — so the seat is the
            # live combat's, through the engine's one reader.
            #
            # The supplied seat wins wherever there is one, which is what keeps
            # a trigger reading its own combat rather than whatever is
            # happening when it resolves. And a flag with no seat and no combat
            # still offers nothing rather than everything: outside combat there
            # is no defending player (CR 506.2), so the card has no legal
            # target, which is the answer rather than a fallback.
            if spec.get("defending_player_only") and seat != defending_seat:
                continue
            # "…**that player** controls" (Fatal Lore). The same arrangement one
            # record over: CR 700.2e's mode choice froze the seat, and the
            # caller holding that record supplies it beside the flag. A flag
            # with no seat offers nothing, for the reason above — this one would
            # otherwise widen to every creature in the game.
            if spec.get("that_player_only") and seat != that_player_seat:
                continue
            for idx, perm in enumerate(player.battlefield):
                if not self._permanent_matches_target_kind(perm, kind, spec, casting_aura):
                    continue
                # "Sacrifice **another** …" — the source cannot pay for itself.
                if spec.get("exclude_source") and perm is source_permanent:
                    continue
                # "target creature **you cast this turn**" (Cycle of Life).
                # CR 701.5a's cast, asked through ``subject_matches`` -- the
                # one reader of a printed noun phrase -- so the picker and
                # the resolution cannot disagree about which creatures answer
                # it. Here rather than in ``_permanent_matches_target_kind``
                # because the phrase names a *seat*, and that method is
                # handed no observer to compare one against.
                if spec.get("cast_by_you_this_turn") and not subject_matches(
                    self, perm, {"cast_by_you_this_turn": True},
                    observer=caster_index, source=source_permanent,
                ):
                    continue
                # "…with power **less than the number of cards in your
                # graveyard**" (Temporary Insanity). The seat-relative bound
                # beside it, asked the same way: "your" is the seat choosing.
                if spec.get("power_vs_count") and not subject_matches(
                    self, perm, {"power_vs_count": spec["power_vs_count"]},
                    observer=caster_index,
                ):
                    continue
                # "…to **another** target creature" on an Aura (Farrel's
                # Mantle): the creature excluded is the one the source is
                # attached to, which is the one that will deal the damage.
                if spec.get("exclude_attached"):
                    from .handlers._common import attached_host

                    if perm is attached_host(self, source_permanent):
                        continue
                # The three combat *relations* a target description can print.
                # Both are asked through ``subject_matches`` — the one reader of
                # what a printed noun phrase means — with the observer and
                # source this loop holds, so the list the picker offers and the
                # set the handler affects are decided by the same function.
                # A flag with nothing to answer it against offers nothing, which
                # is the direction that cannot widen a target description.
                if (
                    spec.get("blocked_by_source")
                    or spec.get("blocking_source")
                    or spec.get("attacking_you")
                    or spec.get("attacked_you_this_turn")
                ):
                    relation = {
                        key: True
                        for key in (
                            "blocked_by_source", "blocking_source", "attacking_you",
                            "attacked_you_this_turn",
                        )
                        if spec.get(key)
                    }
                    if not subject_matches(
                        self, perm, relation,
                        observer=caster_index,
                        source=ability_source or source_permanent,
                    ):
                        continue
                # Whatever the printed noun phrase says beyond its head noun
                # ("a creature **with defender**", Portcullis Vine). The same
                # matcher the payment path runs, so the list offered here and
                # the list accepted there are the same list — a picker offering
                # an ineligible permanent would have its answer silently
                # replaced by the deterministic pick.
                if not subject_matches(
                    self, perm, spec.get("filter"), defending=defending_seat
                ):
                    continue
                if not paying_a_cost:
                    if for_cast:
                        ok, _ = self._validate_cast_targets(
                            card, caster_index,
                            target_player_index=seat, target_permanent_index=idx,
                            optional_cost_payments=optional_cost_payments,
                            mode_index=mode_index,
                        )
                        if not ok:
                            continue
                    else:
                        # The spec goes with the object. ``ability_source``
                        # says an *ability* is choosing; the spec says what that
                        # one ability announced, which is what Wall of Shadows'
                        # "abilities that can target only Walls" asks about and
                        # which the source object alone cannot answer.
                        #
                        # **Not asked of "a source of your choice".** A source
                        # is chosen, not targeted (CR 609.7a; CR 115.1 lists
                        # what targets), so shroud, hexproof and protection —
                        # each a statement about being *targeted* — have no
                        # bearing on whether it may be chosen. Asked anyway, a
                        # warded permanent was treated differently from its
                        # plain twin 390 times in 1,400, over the 28 abilities
                        # in the pool that choose a source
                        # (tests/engine/test_chosen_source_census.py).
                        if not choosing_a_source and not self._can_be_targeted(
                            perm, card, caster_index=caster_index,
                            ability_source=ability_source, source_spec=spec,
                        ):
                            continue
                        # Apply the activated ability's own target restriction (e.g.
                        # Royal Assassin's tapped-only, Nettling Imp's non-Wall) so it
                        # offers only what it could legally affect at resolution.
                        if ability_instruction is not None and not self._ability_target_legal(
                            ability_instruction, perm,
                            candidate_seat=seat, controller_index=caster_index,
                            source_permanent=source_permanent,
                            defending=defending_seat,
                            that_player=that_player_seat,
                        ):
                            continue
                targets.append({
                    "kind": "permanent",
                    "seat": seat,
                    "index": idx,
                    "key": f"{seat}-{idx}",
                    "name": perm.card.name,
                })
        # Circle of Protection: the chosen source may also be a spell of the named
        # color on the stack — fold those into the same target list.
        if spec.get("also_stack"):
            targets += self._enumerate_stack_targets(
                caster_index,
                card,
                {
                    "stack_color_filter": spec.get("color_filter"),
                    "stack_any_colors": spec.get("any_colors"),
                },
            )
        return targets

    def _ability_target_legal(
        self, instruction, perm: Permanent, *,
        candidate_seat=None, controller_index=None, source_permanent=None,
        defending: int | None = None,
        that_player: int | None = None,
    ) -> bool:
        """Whether *perm* satisfies an activated ability instruction's own target
        restriction (beyond the text-derived kind).

        *defending* is CR 506.2's seat, resolved by the caller and handed down
        for the generic tail's ``subject_matches`` -- a printed "defending
        player controls" is a narrowing like any other and must be tested, not
        dropped, at the one place that decides what a picker offers.

        *that_player* is CR 603.10's seat, travelling for exactly that reason
        one phrase over: "target creature or planeswalker **that player**
        controls" (Chandra's Incinerator) is a narrowing ``subject_matches``
        refuses outright unless it is given the seat, and refusing is what an
        empty picker looks like. The caller is the only holder -- the seat was
        frozen into the trigger's context by the fire site -- so it is handed
        down rather than re-derived, which is what keeps the picker and the
        resolution naming one player.
        """
        instruction = _targeting_step(instruction) or instruction
        if instruction.kind == "destroy_target_permanent":
            # Every seat this gate can be given, because ``subject_matches``
            # refuses a seat-relative narrowing it cannot answer and a refusal
            # here is an empty picker: "you own" (Despotic Scepter) wants the
            # observer, "defending player controls" (Necrite, Goblin Vandal)
            # wants CR 506.2's seat, "that player controls" (Feline Sovereign)
            # wants the one the trigger froze, and "blocking this creature"
            # (Urborg Panther) wants the ability's own source.
            return self._destroy_target_legal(
                instruction.payload, perm,
                observer=controller_index,
                source=source_permanent,
                defending=defending,
                that_player=that_player,
            )
        if instruction.kind == "mark_non_wall_target_to_attack":
            # The whole noun phrase, not its first two words: "the active
            # player has controlled continuously since the beginning of the
            # turn" narrows it further, and the picker offering a creature the
            # handler will refuse is the two-readers failure this gate exists
            # to prevent. One reader answers both.
            from .handlers.combat import forced_attacker_is_legal

            return forced_attacker_is_legal(self, perm)
        if instruction.kind == "grant_flying_and_delayed_destruction":
            # Stone Giant: "Target creature you control with toughness less than
            # this creature's power." Only the activating player's creatures with
            # toughness below the source's power are legal.
            if candidate_seat is not None and controller_index is not None and candidate_seat != controller_index:
                return False
            if source_permanent is not None and perm.effective_toughness >= source_permanent.effective_power:
                return False
            return perm.is_creature
        if instruction.kind == "set_base_pt_target_until_eot" and instruction.payload.get("exclude_self"):
            # Sorceress Queen: "Target creature other than this creature."
            return source_permanent is None or perm is not source_permanent
        if instruction.kind == "set_source_base_pt_from_target":
            # Sentinel: "target creature blocking or blocked by this creature";
            # Sworn Defender: "…blocking or being blocked by this creature"
            # — the same in-combat relation the handler re-checks at resolution
            # (CR 608.2b), asked here so the ability is refused with nothing
            # paid when no such creature exists (CR 602.2b via 601.2c) and the
            # picker offers exactly what the effect can read.
            if not perm.is_creature:
                return False
            if instruction.payload.get("in_combat_with_source"):
                return source_permanent is not None and any(
                    perm is opponent
                    for opponent in self.creatures_in_combat_with(source_permanent)
                )
            return True
        if instruction.kind == "steal_creature_while_tapped_and_weaker":
            # Old Man of the Sea: only creatures at or below its own power.
            if not perm.is_creature:
                return False
            return source_permanent is None or perm.effective_power <= source_permanent.effective_power
        if instruction.kind == "steal_target_linked_to_source":
            # Willow Satyr's "target legendary creature" / Rubinia Soulsinger's
            # "target creature" — the same payload filter the handler tests at
            # resolution, asked here so the picker offers exactly what the
            # resolution will accept.
            #
            # **Seasinger's "whose controller controls an Island" is dropped
            # here**, and swapping this to ``subject_matches`` is not the fix:
            # this same arm serves Orcish Squatters' "target land **defending
            # player** controls", a seat that belongs to the combat rather than
            # to the permanent, and ``subject_matches`` refuses that key
            # outright — so the swap trades a widened picker for an empty one.
            # The two phrases want different readers; see the W1G2 report.
            return permanent_matches_filter(perm, instruction.payload)
        if instruction.kind == "grant_regeneration_to_target_creature":
            # Elephant Graveyard's "target Elephant" — the same subtype filter
            # _grant_regeneration_shield enforces at resolution. Death Ward's
            # payload is empty, so every creature passes.
            return perm.is_creature and permanent_matches_filter(perm, instruction.payload)
        if instruction.kind == "produce_mana_instead":
            # Quarum Trench Gnomes' "target Plains" — the same subtype filter
            # the handler tests at resolution, asked here so the ability is
            # refused with nothing paid when no such land exists (CR 602.2b via
            # 601.2c) and the picker offers exactly what the swap can reach.
            targets = instruction.payload.get("targets") or {}
            return permanent_matches_filter(perm, targets.get("filter") or {})
        if instruction.kind == "tap_target_permanent":
            # Ali Baba's "target Wall" (and any other parsed tap-target filter);
            # Icy Manipulator's payload is empty, so everything passes.
            #
            # Through ``subject_matches``, **not** the pure matcher. Three of
            # the keys this family's payloads carry are questions only the game
            # can answer — a keyword is layer 6, "you don't control" is a seat,
            # "that's attacking you" is a combat record — and the pure matcher
            # ignores every one of them rather than refusing. Ignored, the
            # printed narrowing is enforced by nobody: Flood tapped a flier,
            # Ice Floe tapped a creature attacking somebody else, Shacklegeist
            # tapped its own controller's creature, and Storm Elemental named
            # a ground creature. All four paid the cost, resolved, and tapped
            # nothing, because the *handler* still reads the filter — which is
            # the shape that makes this silent.
            # Every seat this gate can be given, exactly as the destroy branch
            # above hands them down and for its stated reason: a seat-relative
            # narrowing ``subject_matches`` cannot answer is one it **refuses**,
            # and a refusal here is an empty picker — CR 603.3c then takes the
            # ability off the stack for having no legal target. "That player
            # controls" (Somnophore) is the seat the trigger's fire site froze
            # and "defending player controls" is CR 506.2's; the caller is the
            # only holder of either, so both travel rather than being
            # re-derived.
            return subject_matches(
                self, perm, instruction.payload,
                observer=controller_index, source=source_permanent,
                defending=defending, that_player=that_player,
            )
        if instruction.kind == "attach_source_to_target":
            # An equip ability (CR 702.6a). The picker's own_only flag has
            # already kept it to the activator's creatures; what is left is the
            # printed narrowing (CR 702.6c's "legendary creature") and whether
            # the Equipment may legally equip this creature at all — protection
            # from its colour (702.16d), the Equipment itself (301.5c). Asked of
            # the same predicate the resolution asks, so a creature offered here
            # is one the attach then lands on.
            # ``attachment_refusal``, not ``equip_refusal``: CR 701.3's action
            # is asked of whichever kind of Attachment printed the ability, and
            # an Aura's legality is its enchant clause (CR 702.5), not
            # CR 301.5's. Asking the Equipment predicate of an Aura refused
            # every host and emptied the picker.
            from .equipment import attachment_refusal

            if not permanent_matches_filter(perm, instruction.payload):
                return False
            # The printed narrowing lives on the ``targets`` filter as well as
            # on the payload root — "other than enchanted creature" (Kjeldoran
            # Pride) is a relative key, which ``permanent_matches_filter`` (the
            # pure half) cannot answer at all. So it is asked of
            # ``subject_matches``, the half that has the game and the source
            # (imported at module scope, not here: a second, function-level
            # import of a module-level name turns it local for the *whole*
            # function and breaks every other branch that reads it).
            described = (instruction.payload.get("targets") or {}).get("filter") or {}
            if described and not subject_matches(
                self, perm, described, observer=controller_index,
                source=source_permanent,
            ):
                return False
            return (
                source_permanent is None
                or attachment_refusal(self, source_permanent, perm) is None
            )
        if instruction.kind == "add_counter_to_target":
            # Tempered Veteran's "target creature with a +1/+1 counter on it" —
            # the same filter the handler enforces at resolution, so the picker
            # offers exactly what the ability could affect. Most counter
            # placements carry an empty filter and every creature passes.
            targets = instruction.payload.get("targets") or {}
            if not perm.is_creature or not permanent_matches_filter(
                perm, targets.get("filter") or {}
            ):
                return False
            # "…on target creature **blocking or blocked by this creature**"
            # (Lesser Werewolf) — the same in-combat relation Sentinel's rewrite
            # carries a dozen lines above, asked here so the ability is refused
            # with nothing paid when no such creature exists (CR 602.2b via
            # 601.2c) and the picker offers exactly what the effect can reach.
            if instruction.payload.get("in_combat_with_source"):
                return source_permanent is not None and any(
                    perm is other
                    for other in self.creatures_in_combat_with(source_permanent)
                )
            return True
        # **The generic tail, and the reason it is not another branch.**
        # Every branch above says the same sentence in its own words: "apply the
        # filter this instruction's payload already carries". A kind absent from
        # the chain fell through to a bare ``return True``, and that is not a
        # missing feature — it is the printed narrowing *dropped at the picker*,
        # silently and in the player's favour. Karakas offered every creature
        # for "target **legendary** creature", Grapeshot Catapult every creature
        # for "target creature **with flying**", Mishra's Factory every creature
        # for "target **Assembly-Worker**"; each of them a shipped card whose
        # ability worked more often than it reads.
        #
        # It is safe as a default rather than as an opt-in list because the
        # compiler will not admit a narrowed line at all unless every key of its
        # filter is in ``TESTABLE_SUBJECT_FILTER_KEYS`` (see
        # ``engine/subject_filters.py``). So a filter that reaches here is one
        # ``subject_matches`` answers in full — and the branches above survive
        # only where the restriction is *not* in the filter (an in-combat
        # relation, the source's own power, the equip legality).
        #
        # ``subject_matches`` rather than ``permanent_matches_filter``: the
        # relative keys are exactly the ones a picker can answer and a pure
        # matcher cannot — "you control" is the activating seat, "another" is
        # the source — and both are already in this method's hands.
        #
        # A description whose slots are *differently* restricted carries one
        # filter per slot, and the picker enumerates one legal set for all of
        # them — so a permanent is offered when **some** slot admits it, never
        # only when every slot does. Garruk, Savage Herald's -2 is the case:
        # slot one is "creature you control", slot two is any creature, and
        # intersecting them would hide every opponent's creature from a bite
        # that is allowed to name one. Per-slot legality stays the handler's.
        targets = instruction.payload.get("targets") or {}
        slot_filters = targets.get("filters")
        if isinstance(slot_filters, list) and len(slot_filters) > 1:
            return any(
                subject_matches(
                    self, perm, slot or {},
                    observer=controller_index, source=source_permanent,
                    defending=defending, that_player=that_player,
                )
                for slot in slot_filters
            )
        described = targets.get("filter")
        if described:
            return subject_matches(
                self, perm, described,
                observer=controller_index, source=source_permanent,
                defending=defending, that_player=that_player,
            )
        return True

    def _permanent_matches_target_kind(self, perm: Permanent, kind: str, spec: dict, casting_aura: bool) -> bool:
        # **Every head noun is a layer-4 question** (CR 613.1d), asked through
        # ``has_type``. It was the effective card's *printed* line here, and
        # ``card.primary_type`` for lands: right for a copy (layer 1 is folded
        # in either way — a Copy Artifact copying a Mox is an "Artifact
        # Enchantment" and is offered as both), wrong for every type an effect
        # adds or takes away. A creature made an artifact (Xenic Poltergeist,
        # Ashnod's Transmogrant) was never offered to Shatter, and a Sol Ring
        # that had stopped being an artifact still was — so CR 608.2b, which
        # re-asks this enumeration at resolution, called that target legal.
        # "…**that isn't enchanted**" (Time Elemental). Asked before the kind
        # switch because the restriction is not about the head noun: the card
        # prints it on "permanent", and a card printing it on "creature" would
        # want the same answer. The pure matcher answers it, so the picker and
        # the handler's ``subject_matches`` call cannot disagree.
        if spec.get("not_enchanted") and not permanent_matches_filter(
            perm, {"not_enchanted": True}
        ):
            return False
        # "…**target enchanted creature**" (Ramses Overdark), the positive twin
        # and asked in the same place for the same reason: the restriction is
        # not about the head noun, and the picker must offer exactly what the
        # handler's matcher would accept — an unenchanted creature offered here
        # is a tap paid for a destroy that then fizzles.
        if spec.get("enchanted_only") and not permanent_matches_filter(
            perm, {"enchanted_only": True}
        ):
            return False
        # **Colour is not about the head noun.** "Target **black** creature"
        # (Exorcist, Spinal Villain) restricts exactly what "target **blue**
        # permanent" (Flash Flood) does, so it is asked once, before the switch,
        # for the reason the two tests above it are: a restriction asked inside
        # one branch is a restriction the other branches drop. It lived in the
        # ``permanent`` branch alone, so a colour-narrowed *creature* target was
        # offered in every colour by any caller with no instruction to delegate
        # to — a cast, a reflexive trigger (CR 603.12) and a trigger choosing
        # its own target all enumerate without one.
        #
        # Layer 5, not the printed line. Deathlace makes a Grizzly Bears black;
        # the *resolution* accepted it and this enumerator did not, so the
        # picker offered nothing while a script could kill it — one question
        # about one permanent with two answers.
        color_filter = spec.get("color_filter")
        if color_filter and color_filter not in perm.effective_colors:
            return False
        # "a black **or red** source of your choice" — the disjunction
        # ``ObjectFilter.any_colors`` spells the same way, asked of the same
        # layer-5 answer as the single-colour test above.
        any_colors = spec.get("any_colors")
        if any_colors and not any(
            colour in perm.effective_colors for colour in any_colors
        ):
            return False
        # "Enchant creature **without flying**" (Roots). Asked here, before the
        # switch, for the same reason the colour tests above it are: an
        # exclusion asked inside one branch is an exclusion every other branch
        # drops, and CR 702.5's [quality] can narrow any of the six enchant
        # nouns. Layer 6, through the same ``has_keyword`` the cast gate asks
        # (``stack/cast_target_validation.permanent_matches_enchant_noun``) — one reading, so
        # the picker cannot offer a host the cast then refuses.
        without_keyword = spec.get("without_keyword")
        if without_keyword and self._has_keyword(perm, without_keyword):
            return False
        if kind == "player_or_planeswalker":
            # "Target player or planeswalker" (Chandra's Magmutt): the only
            # permanents in the union are planeswalkers — the player faces were
            # already added by the seat loop above.
            return perm.has_type("planeswalker")
        if kind == "planeswalker":
            # "target planeswalker" alone (Sparkhunter Masticore), with no player
            # face in the union. Through `has_type` rather than the printed line,
            # because a planeswalker is a computed type like any other (CR 613
            # layer 4).
            return perm.has_type("planeswalker")
        if kind in ("creature", "any", "divided"):
            # Volcanic Eruption: a divided spell that targets Mountains, not creatures.
            land_filter = spec.get("land_filter")
            if land_filter:
                if not perm.has_type("land"):
                    return False
                # CR 305.7: setting a land's subtype replaces its old ones, so
                # a Mountain turned into an Island is NOT a legal "target
                # Mountain". Matching printed-or-override made it both.
                return perm.has_type(land_filter)
            # is_creature so animated lands (Kormus Bell / Living Lands) are legal
            # targets for creature-targeting spells, abilities, and Auras.
            # CR 115.4: "any target" also admits planeswalkers.
            if not perm.is_creature:
                if kind == "any" and perm.has_type("planeswalker"):
                    return True
                return False
            if spec.get("enchant_wall"):
                return perm.has_type("wall")
            # Forcefield: only unblocked attacking creatures are legal choices.
            if spec.get("unblocked_attacker") and not (perm.attacking and not perm.blocked):
                return False
            # Singing Tree: only currently-attacking creatures are legal choices.
            if spec.get("attacking_only") and not perm.attacking:
                return False
            # Righteousness, Sorrow's Path: only creatures that are currently
            # blocking are legal choices. The narrower half of the `any_states`
            # union below, asked of the same `state_holds` table so a picker and
            # a resolution cannot disagree about what "blocking" means. Enforced
            # here as well as at resolution because CR 602.2b refuses an
            # activation outright when no legal target exists — the cast side
            # reached the same answer through its own `_validate_cast_targets`
            # probe, and an *ability* narrowed this way had nothing at all.
            if spec.get("blocking_only") and not state_holds(perm, "blocking"):
                return False
            # "target **blocked** attacking creature" (General Jarkeld). The
            # other end of the same relation, asked exactly as
            # `permanent_matches_filter` asks it so the picker and the
            # resolution cannot disagree — CR 509.1h's blocked creature is an
            # attacking one that has blockers declared for it.
            if spec.get("blocked_only") and not (
                getattr(perm, "attacking", False) and getattr(perm, "blocked", False)
            ):
                return False
            # The Legends pinger cycle: "target attacking or blocking creature".
            # Enforced here as well as at resolution, because CR 602.2b refuses
            # the activation outright when no legal target exists — a pinger
            # with nothing in combat to shoot must cost nothing rather than
            # resolve at whatever the picker happened to offer.
            any_states = spec.get("any_states")
            if any_states and not any(
                state_holds(perm, word) for word in any_states
            ):
                return False
            # "…creatures **without flying**" (Rock Slide). Asked of layer 6
            # through the same accessor `flying_only` beside it uses, so a
            # creature *granted* flying is excluded exactly as a printed flyer
            # is (CR 613.1f) and one that lost it is offered. Enforced here as
            # well as at resolution, for `blocked_only`'s reason: a narrowing
            # the picker does not apply is one CR 601.2c then admits.
            if any(
                self._has_keyword(perm, str(word))
                for word in spec.get("without_keywords") or ()
            ):
                return False
            # Island of Wak-Wak: only flying creatures are legal choices.
            if spec.get("flying_only") and not self._has_keyword(perm, "flying"):
                return False
            # Ali Baba: only Walls are legal choices.
            if spec.get("wall_only") and not perm.has_type("wall"):
                return False
            return True
        if kind == "artifact":
            if not perm.has_type("artifact"):
                return False
            # Guardian Beast: noncreature artifacts it protects can't be enchanted.
            if casting_aura and self._untapped_artifact_protector_active(perm):
                return False
            return True
        if kind == "land":
            if not perm.has_type("land"):
                return False
            if casting_aura and _cant_be_enchanted_by_auras(perm):
                return False
            # "Enchant **Swamp**" (Spreading Algae). The subtype half of
            # CR 702.5's [quality] on a land clause, narrowing the same land
            # picker the bare noun builds — and asked of `has_type`, which is
            # CR 613 layer 4 and the same reading `land_filter` above and
            # `exclude_swamp` below already take: CR 305.7 makes a Swamp turned
            # into an Island stop being one, so it stops being offered here and
            # the CR 704.5m sweep bins an Aura already sitting on it.
            enchant_land_type = spec.get("enchant_land_type")
            if enchant_land_type and not perm.has_type(enchant_land_type):
                return False
            if spec.get("exclude_swamp"):
                # Same CR 305.7 point: a Swamp turned into an Island is no
                # longer a Swamp, so "target non-Swamp land" may target it.
                if perm.has_type("swamp"):
                    return False
            return True
        if kind == "permanent":
            # Colour is settled above the switch; what is left here is the one
            # narrowing only this branch has.
            if spec.get("enchant_enchantment"):
                return perm.has_type("enchantment")
            return True
        return False

    def _enumerate_cost_hand_cards(
        self, caster_index: int, card: CardDefinition, spec: dict | None = None,
        *, for_cast: bool,
    ) -> list[dict]:
        """The cards that may pay a "discard a card" cost.

        **What is withheld is the whole difference between the two callers.**
        Casting from the hand withholds the spell: CR 601.2a puts it on the
        stack before its costs are paid, so it is not in the hand to be
        discarded (with two copies in hand the *other* is a legal payment, so
        exactly one occurrence goes — the one the hand lookup will cast).
        Casting from anywhere else withholds nothing, for the same reason
        activating does not: the object on the stack came from another zone, so
        a copy sitting in hand is an ordinary card like any other.

        A hint, not the authority: both payment paths re-check the answer on the
        way back in, so a client that offers a whole hand cannot turn the cost
        into "discard nothing".
        """
        hand = self.players[caster_index].hand
        # …and only when the hand is the zone the spell left. A cast from the
        # graveyard (Demonic Embrace) put nothing of the caster's hand on the
        # stack, so a second copy held there is an ordinary card and a legal
        # payment; withholding it would hide the only discard a one-card hand
        # can make.
        leaves_hand = (spec or {}).get("cast_zone", "hand") == "hand"
        spell_index = (
            next((i for i, held in enumerate(hand) if held.name == card.name), None)
            if for_cast and leaves_hand
            else None
        )
        # "Discard a **land card or Shrine card**" (Sanctum of Shattered
        # Heights). The narrowing is applied with the same reader the charger
        # uses, so the picker cannot offer a card the payment then refuses —
        # which is the failure this enumerator exists to prevent, and which the
        # graveyard picker below already had to be fixed for.
        alternatives = (spec or {}).get("filters") or ()
        return [
            {"kind": "hand_card", "seat": caster_index, "hand_index": index, "name": held.name}
            for index, held in enumerate(hand)
            if index != spell_index and card_matches_any(held, alternatives)
        ]

    def _enumerate_graveyard_creatures(
        self, caster_index: int, spec: dict, *, source_card=None
    ) -> list[dict]:
        targets: list[dict] = []
        # "Cards in graveyards can't be the targets of spells or abilities."
        # (Ground Seal.) Asked **here**, in the one enumeration of graveyard
        # targets, so every reader of the list inherits the answer: the picker
        # offers nothing, CR 601.2c's cast gate and CR 602.2b's activation gate
        # refuse with nothing paid, and a trigger that must target one has no
        # legal choice (CR 603.3d). A *cost* paid out of a graveyard (Necropolis)
        # is not a target and keeps its list — the card's ruling: "Abilities
        # that don't target cards in graveyards … can still affect those cards."
        if not spec_is_a_cost(spec):
            from .target_immunity import graveyard_cards_untargetable

            if graveyard_cards_untargetable(self) is not None:
                return targets
        # Reconstruction returns an *artifact* card, Raise Dead a creature card,
        # Chandra a red instant or sorcery. One template with the type as data,
        # and one predicate shared with the cast-time re-check and the handler
        # (`engine/handlers/_common.py`) — a picker that offers what
        # resolution then refuses is the bug this module exists to prevent, and
        # it was live: the re-check asked only "is it a creature card?".

        # A **cost**'s narrowing beyond its head type ("Exile a *black* card
        # from your graveyard") rides the spec as ``cost_filter`` and is asked
        # through the matcher the charger accepts by, so the two cannot
        # disagree about a phrase the target vocabulary above has no key for.
        cost_filter = spec.get("cost_filter") if spec.get("exile_cost") else None

        def eligible(card) -> bool:
            if cost_filter:
                from .handlers._common import _card_matches_filter

                if not _card_matches_filter(card, cost_filter):
                    return False
            return graveyard_card_matches(spec, card)

        for seat, player in enumerate(self.players):
            if spec.get("own_graveyard_only") and seat != caster_index:
                continue
            # "from **an opponent's** graveyard" (Misinformation) — CR 102.2/102.3's
            # own-seat exclusion applied to the *pile* the cards are chosen
            # from. The mirror of the scope above and offered for the same
            # reason: a picker that ignored the printed word would let the
            # caster reach into their own graveyard, which is a different card.
            if spec.get("opponent_graveyard_only") and seat == caster_index:
                continue
            # "…**another** target artifact card from your graveyard"
            # (Junk Diver). The printed word excludes one *slot* rather than one
            # kind of card, so it is asked beside the predicate rather than
            # inside it — through the one reader the handler also asks, which is
            # what stops this picker offering a card resolution then declines.
            # Per pile, because a slot number means nothing without the seat.
            excluded = excluded_graveyard_slot(spec, player.graveyard, source_card)
            # The card being cast, when the cast is out of this very pile
            # (CR 601.2a: it is on the stack before CR 601.2c chooses anything —
            # see ``targeting.CAST_FROM_GRAVEYARD``). The caster's own pile
            # only: a deck repeats one immutable definition per copy and both
            # decks may hold it, so the same object in an opponent's graveyard
            # is a different card and a legal target.
            leaving = (
                _cast_from_graveyard_slot(spec, player.graveyard, source_card)
                if seat == caster_index else None
            )
            for idx, card in enumerate(player.graveyard):
                if idx != excluded and idx != leaving and eligible(card):
                    targets.append({"kind": "graveyard", "seat": seat, "index": idx, "name": card.name})
        return targets


#: The payload keys a composed instruction nests its steps under, in the order
#: :func:`engine.targeting._from_instructions` reads them. Held to that order on
#: purpose: the picker's *kind* comes from there and its *restriction* comes from
#: here, and two walks that disagreed would offer a target the resolution then
#: declines — the two-readers failure this file exists to prevent.
_COMPOSED_STEP_KEYS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "unless_player_pays": ("unpaid", "paid"),
    # An offer's *declined* branch is read last and is read at all for
    # CR 601.2c's reason: Arcum's Whistle chooses its creature as the ability is
    # activated, before anybody is offered the payment.
    "may": ("action", "then", "otherwise"),
}


def _targeting_step(instruction):
    """The instruction inside *instruction* that actually names a target, or
    None when *instruction* is not a composition.

    An ability whose whole effect sits behind an offer or a condition carries
    its printed target restriction on the *inner* step, and the enumerator is
    handed the outer one. Without this, Arcum's Whistle's "target non-Wall
    creature the active player has controlled continuously since the beginning
    of the turn" was a noun phrase the picker never asked about: it offered
    every creature on the board, Walls and new arrivals included, and the
    handler then refused them — a restriction enforced by nothing, which is
    this file's own failure mode.
    """
    keys = _COMPOSED_STEP_KEYS.get(instruction.kind)
    if keys is None:
        return None
    for key in keys:
        for step in instruction.payload.get(key) or ():
            found = _targeting_step(step)
            if found is not None:
                return found
            if step.kind not in _COMPOSED_STEP_KEYS:
                return step
    return None
