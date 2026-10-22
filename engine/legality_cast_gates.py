"""The gates a spell's announcement passes before any cost is paid (CR 601.2c).

Three questions, asked by the cast path before any cost is paid — and the
first, with the modes beside it, by the AI's proposal filter and the web's
castable highlight too, so "nothing to name" is one answer everywhere:

* is there **anything to name** at all
  (:meth:`CastTargetGatesMixin.no_legal_cast_target_refusal`), and for a modal
  spell, in which modes (:meth:`CastTargetGatesMixin.announceable_modes`);
* is what was **named** legal — a permanent, a card in a graveyard, a player,
  each entry of a division (:meth:`CastTargetGatesMixin.cast_target_refusal`);
* is it **as many** as the spell prints
  (:meth:`CastTargetGatesMixin.cast_target_count_refusal`).

Each is answered against the list the picker was handed
(``engine/legality_enumeration.py``), and
:meth:`CastTargetGatesMixin._described_cast_target_slots` is the predicate the
resolution's CR 608.2b re-check asks too, so a target turned illegal in
response is illegal at resolution exactly as it would have been here. A target
**on the stack** is ``engine/legality_stack.py``'s.
"""

from __future__ import annotations

from .models import CardDefinition
from .divided_damage import divided_entry
from .oracle import compile_card_oracle
from .oracle_types import cost_target_count
from .targeting import (
    GRAVEYARD_TARGET_KIND,
    as_cast_from,
    cast_target_slot,
    derive_cast_spec,
    spec_is_a_cost,
    spec_offers_a_player,
    spec_roles,
)
from .legality import (
    _unnamed_single_pile_refusal,
    _UNCHECKED_CAST_TARGET_KINDS,
    cast_target_obligation,
    exact_target_count,
)


class CastTargetGatesMixin:
    """The CR 601.2c gates a spell's announcement passes before a cost is
    paid. Composed onto ``Game`` beside ``LegalityMixin``."""

    def mode_announcement_refusal(
        self, caster_index: int, card: CardDefinition, mode_index: int, *,
        optional_cost_payments: dict | None = None,
        x_value: int | None = None,
    ) -> str | None:
        """Why mode *mode_index* of a modal spell has **no legal announcement
        at all** right now (CR 601.2c), or None when one exists.

        "Could this mode be cast, if the caster picked well?" — the question
        with nothing named, asked by the three callers that pick a mode before
        any target: the web's castable highlight, the mode list the client is
        sent (a mode that cannot be announced is not offered), and the AI's
        mode chooser. The same gates ``_cast_onto_stack`` runs for a named
        announcement, with nothing named, so a mode this passes is one some
        cast of it will not be refused for want of a target:

        * a **roles** mode ("destroy target artifact and target enchantment",
          Hull Breach) needs a whole chain — the picker's own walk;
        * every other mode needs its mandatory target to exist
          (:meth:`no_legal_cast_target_refusal`, the per-kind arm's "nothing
          named" half, and :meth:`cast_stack_target_refusal` for a target on
          the stack).
        """
        program = compile_card_oracle(card)
        if not program.modes or not 0 <= mode_index < len(program.modes):
            return f"{card.name}: no mode {mode_index!r}"
        spec = derive_cast_spec(
            card, program, optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
        if spec_roles(spec):
            if self.targeting_bans:
                return f"no valid target for {card.name}"
            if not self._role_target_walk(caster_index, card, spec, (), for_cast=True):
                return f"no valid target for {card.name}"
            return None
        ok, reason = self._validate_cast_targets(
            card, caster_index, None, mode_index=mode_index, x_value=x_value,
            optional_cost_payments=optional_cost_payments,
        )
        if not ok:
            return reason
        unaimed = self.no_legal_cast_target_refusal(
            caster_index, card, optional_cost_payments=optional_cost_payments,
            x_value=x_value, mode_index=mode_index,
        )
        if unaimed is not None:
            return unaimed
        return self.cast_stack_target_refusal(
            caster_index, card, None, mode_index=mode_index,
        )

    def announceable_modes(
        self, caster_index: int, card: CardDefinition, *,
        optional_cost_payments: dict | None = None,
        x_value: int | None = None,
    ) -> list[int]:
        """The supported modes of a modal spell that have a legal announcement
        right now, in printed order — every mode
        :meth:`mode_announcement_refusal` does not refuse.

        Empty for a card that is not modal, and for one whose mode **an
        opponent** chooses (CR 700.2e): its caster picks no mode, so "which
        mode could I cast" is not a question it is asked.
        """
        program = compile_card_oracle(card)
        if not program.modes or program.mode_chooser is not None:
            return []
        return [
            index for index, mode in enumerate(program.modes)
            if mode.supported and self.mode_announcement_refusal(
                caster_index, card, index,
                optional_cost_payments=optional_cost_payments, x_value=x_value,
            ) is None
        ]

    def _described_cast_target_slots(
        self, caster_index: int, card: CardDefinition, spec: dict,
        *, optional_cost_payments: dict | None = None,
        mode_index: int | None = None,
    ) -> set[tuple[int, int]]:
        """Every battlefield slot *card*'s printed target description admits
        **now**, as ``(seat, index)``.

        The one answer to "does this permanent still match what the spell
        printed?", asked by both ends of a spell's life: CR 601.2c as it is
        announced (:meth:`cast_target_refusal`) and CR 608.2b as it resolves
        (:meth:`illegal_targets_refusal`). It is the picker's own enumeration —
        every narrowing a spec carries (``filter``, ``own_only``,
        ``attacking_only``, ``defending_player_only`` …) and every per-kind arm
        ``_validate_cast_targets`` re-checks a single slot with — so the
        announcement and the resolution cannot come to disagree about what a
        printed word means. Two copies of that list is how "nonblack" came to
        be enforced at announcement and forgotten at resolution.

        *optional_cost_payments* is the announcement *spec* was derived under
        (CR 702.33g), handed on so the per-candidate probe judges each slot
        against that same spec rather than against the card's every arm.
        *mode_index* is the mode it was derived under, handed on for the same
        reason: the probe's per-kind arm has to read the chosen mode's
        instruction, not the first one's.
        """
        valid = self._enumerate_targets(
            caster_index, card, spec, for_cast=True,
            optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
        return {
            (t["seat"], t["index"]) for t in valid
            if t.get("kind") == "permanent" and t.get("index") is not None
        }

    def no_legal_cast_target_refusal(
        self, caster_index: int, card: CardDefinition, *,
        optional_cost_payments: dict | None = None,
        x_value: int | None = None,
        mode_index: int | None = None,
        from_zone: str = "hand",
    ) -> str | None:
        """CR 601.2c's first half: a spell that must announce a target cannot
        be cast while **no legal target exists**. Returns the refusal, or None.

        The cast-side twin of the last paragraph of
        :meth:`activation_target_refusal`, and it exists for the reason that
        method does. ``_validate_cast_targets`` answers "is there anything to
        aim at?" in a per-kind arm keyed on the spell's *primary* instruction,
        so the question was asked of eleven instruction kinds and of no spell
        whose first instruction is a wrapper: "Destroy target artifact or
        enchantment. Draw two cards." on an empty board was announced, paid
        for, destroyed nothing and drew two — a cantrip for the price of a
        removal spell. Disenchant, the same first sentence alone, was refused.

        One predicate instead of an arm per kind: the slot the spell must fill
        (:func:`cast_target_obligation`) against the list the picker is handed
        (``_enumerate_targets``), so "the browser offers nothing" and "the
        engine refuses" are one fact. The AI's proposal filter and the web's
        castable highlight ask this same method.

        What it deliberately leaves alone:

        * a target **on the stack** alone (``stack``) — its "is there a spell
          to name?" belongs to the stack gates beside
          :meth:`cast_stack_target_refusal`. "Target spell **or permanent**"
          (the Laces) is answered here, over both zones, because a board is
          half of its answer;
        * a standing **targeting ban** (Peace Talks) — ``targeting_ban_refusal``
          already refused, and under a ban the enumeration is empty for a
          reason that is not this rule's;
        * everything :func:`cast_target_obligation` declines: a mode an
          opponent chooses, roles, divided spells, and every announcement that
          may name nobody.

        **A modal spell is asked about its announced mode** (*mode_index*; a
        cast naming none is the mode-0 cast it resolves as), so "the chosen
        mode has no legal target" is this refusal for a Charm exactly as it is
        for the one-sentence spell printing the same words.

        Whatever the caller named is not consulted. With no legal target in
        existence a named one is illegal by construction, and
        :meth:`cast_target_refusal` says so in its own words one call later.
        """
        if card.primary_type not in ("instant", "sorcery"):
            return None
        if self.targeting_bans:
            return None
        spec = cast_target_obligation(
            card, compile_card_oracle(card),
            optional_cost_payments=optional_cost_payments, x_value=x_value,
            mode_index=mode_index,
        )
        if spec is None or spec.get("kind") == "stack":
            return None
        # *from_zone*: a spell cast out of a graveyard is not itself a card in
        # that graveyard by the time targets are chosen (CR 601.2a), so it is
        # not what makes "a legal target exists" true. Read onto the spec by
        # the reader ``derive_cast_spec`` uses, so this list is the picker's.
        spec = as_cast_from(spec, from_zone)
        offered = self._enumerate_targets(
            caster_index, card, dict(spec), for_cast=True,
            optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
        if not offered:
            return f"no valid target for {card.name}"
        # CR 601.2c: "two target creatures" needs **two** to exist, not one. A
        # printed count names that many different objects (CR 115.3,
        # ``distinct_targets``), so with fewer legal ones no announcement is
        # possible and the spell cannot be cast — the same refusal as above
        # with a bigger number, asked through the same list.
        #
        # The **printed** number only. "X target creatures" is not held to an
        # announced X here: CR 601.2b settles X first — "X can't be greater
        # than the number of snow lands you control" (Winter's Chill) is an
        # illegal X whatever is on the table — and this method runs above that
        # check, so a shortfall against X is `cast_target_count_refusal`'s,
        # asked below the X resolution where the number is final.
        slot = cast_target_slot(
            card, compile_card_oracle(card),
            optional_cost_payments=optional_cost_payments, mode_index=mode_index,
        )
        required = (
            exact_target_count(slot[0], slot[1], None) if slot is not None else None
        )
        if required and spec.get("distinct_targets") and len(offered) < required:
            return (
                f"{card.name} needs {required} targets and only "
                f"{len(offered)} can be chosen"
            )
        return None

    def cast_target_refusal(
        self, caster_index: int, card: CardDefinition, *,
        target_player_index=None, target_permanent_index=None,
        target_permanent_ids=None, from_zone: str = "hand",
        optional_cost_payments: dict | None = None,
        mode_index: int | None = None,
        divided_targets=None, target_stack_item=None,
        x_value: int | None = None,
    ) -> str | None:
        """CR 601.2c: a **named** target — a battlefield permanent, a slot in a
        graveyard, or a **player** — must be a legal one, checked before any
        cost is paid. Returns the refusal, or None.

        **A player is a target like any other, and it was the one this gate
        did not read.** A seat and a *chosen player* reach a cast through one
        field (``target_player_index``), which is why the gate left it alone:
        beside a permanent it is the battlefield that permanent sits on. But
        which of the two it is can be told from the announcement itself —
        :meth:`_cast_player_target_refusal` says how — and until it was, every
        narrowing a player phrase prints was the picker's alone. "Target
        **opponent**" was castable at the caster (Duress, Coercion, Bribery: 34
        shipped spells), and a player with shroud (Ivory Mask) or one who had
        left the game (CR 800.4a) could be named by any of the pool's 181
        spells that can target a player; Lightning Bolt dealt its 3.

        *divided_targets* is CR 601.2d's list and each entry of it is a target
        (a face where the slot is None): the cast path only bounds-checked it,
        so "divided as you choose among any number of **target creatures**"
        could be announced at a Forest, at a creature with protection from the
        spell's colour, or at a face the phrase never admits.

        **For a modal spell, legal for the mode it was announced with**
        (*mode_index*, CR 601.2b before CR 601.2c). This gate used to return
        None for every modal spell, on the ground that its derived spec was
        mode 0's; the spec is now derived per mode
        (``targeting.derive_cast_spec(mode_index=)``), which is the same
        derivation the client's mode picker is sent and the same one the
        resolution re-asks. Left to the per-kind arms, a mode named **by id**
        was checked by nobody — the arms read the index — so "Destroy target
        artifact" (Hull Breach) accepted a creature, and a mode whose kind has
        no arm (damage, a keyword grant, an exile, phasing) accepted anything
        by either spelling: 1,066 of 1,516 census casts naming an illegal
        permanent for a mode were accepted, and 220 of those then acted on a
        permanent nobody named.

        The cast-side twin of :meth:`activation_target_refusal`, and it exists
        for the same reason that one replaced a per-kind if-chain in
        ``activation.py``: ``_validate_cast_targets`` checks the target of the
        instruction kinds it has arms for, so a card whose primary instruction
        is a ``sequence`` wrapper — every "Destroy target artifact. You gain
        life…" — reached no arm and had its target unchecked. Divine Offering
        could be cast on Grizzly Bears.

        It cannot live inside ``_validate_cast_targets``, which is what makes
        this a second function rather than one more check there:
        ``_enumerate_targets(for_cast=True)`` probes each candidate *through*
        that method, so asking it from inside would recurse. Called beside it
        instead, from the one cast path, before the mana is spent.

        Only what the caller **named** is checked here. "Is there any legal
        target at all?" is :meth:`no_legal_cast_target_refusal`'s question,
        asked one call earlier on the cast path (it was the arms' own, and the
        arms only reach the spells whose first instruction they name); this
        one answers "is the one you named among the ones the picker would have
        offered?", which is idiom #9 — the picker's enumeration is a hint and
        the engine re-checks the answer.

        **One shape is the exception, and it is the exception because the count
        itself was announced**: a spell whose targets are sized by a CR 601.2b
        optional additional cost (Primitive Justice's "for each additional
        {1}{R} you paid, destroy **another** target artifact"). CR 601.2c fixes
        the number of targets one step after that payment, so "how many did you
        name?" is answerable here and nowhere else — *optional_cost_payments* is
        the announcement, passed down from the one cast path. A caster who takes
        three offers with two artifacts on the table cannot make a legal
        announcement, and CR 601.2c makes that an uncastable spell rather than
        an ineffective one: the refusal lands before any mana is spent.

        That was the engine's only enforced target count, and this docstring
        said so: "there is no ``min_targets`` in this engine". A **printed**
        exact count ("two target creatures") and an **announced X** ("X target
        creatures") are counted now too, by :meth:`cast_target_count_refusal`
        — a method of its own because X is not a number until below the X
        resolution, which is later in the cast than this gate runs. What is
        still a ceiling the announcement may fall short of is the count that
        prints one: "up to N", "any number of", and "one or more target
        creatures" (Heaven's Gate and its four colour siblings), whose floor of
        one is :meth:`no_legal_cast_target_refusal`.
        """
        if card.primary_type not in ("instant", "sorcery"):
            # **A permanent spell does not target.** ``derive_cast_spec`` reads
            # the *card*, so Niambi, Esteemed Speaker's "when this creature
            # enters, return another target creature you control" comes back as
            # a creature spec — but that is the ETB trigger's target, chosen
            # when the trigger goes on the stack (CR 603.3d), long after this
            # spell was announced. Gating the cast on it refuses to cast the
            # creature at all. An Aura *is* targeted (CR 115.1b) and its enchant
            # target has its own arm in ``_validate_cast_targets``.
            return None
        program = compile_card_oracle(card)
        if program.modes and program.mode_chooser is not None:
            # "**An opponent** chooses one —" (CR 700.2e): the caster names no
            # target as it casts, because it does not yet know which mode it
            # would be naming one for. ``arm_modal_mode_targets`` asks after
            # the answer, over this same enumeration.
            return None
        # Under the announcement where there is one (CR 702.33g): a target
        # printed only in a kicked half belongs to a kicked cast alone, so the
        # spec the named targets are judged against is the one that cast
        # describes. Read as the whole card, Falling Timber is two roles —
        # which the branch below hands to ``_validate_cast_targets`` — and the
        # one target of an *unkicked* Falling Timber was then checked by
        # nobody: it could be aimed at a land.
        #
        # …and under the **mode** (CR 601.2b): Healing Salve's mode 0 targets a
        # player and its mode 1 a creature, so a modal spell judged against
        # mode 0's enumeration refuses a legal cast — which is why this gate
        # declined modal spells until the spec could be asked per mode.
        spec = derive_cast_spec(
            card, program, from_zone=from_zone,
            optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
        if spec is None or spec.get("kind") in _UNCHECKED_CAST_TARGET_KINDS:
            return None
        if spec_roles(spec):
            # A spell naming several targets of *different* kinds (Glyph of
            # Delusion's Wall and the creature that Wall blocked) has one spec
            # per role and a relation between them. ``_validate_cast_targets``
            # already checks the whole announcement through
            # ``_role_targets_legal``; one flat enumeration here would compare
            # the second target against the first role's list and refuse a
            # legal cast.
            return None
        named_ids = [pid for pid in (target_permanent_ids or []) if isinstance(pid, int)]
        indices = (
            [i for i in target_permanent_index if isinstance(i, int)]
            if isinstance(target_permanent_index, list)
            else ([target_permanent_index] if isinstance(target_permanent_index, int) else [])
        )
        # CR 601.2c's *count*, for the one shape that has one (see the
        # docstring). Above the "nothing was named" return below, because
        # naming nothing is precisely one of the announcements this refuses —
        # and above the graveyard branch, which no cost-sized announcement
        # reaches.
        required = cost_target_count(spec.get("cost_targets"), optional_cost_payments)
        if required is not None:
            # Ids are the precise channel and indices the legacy one; a seat is
            # part of an index's identity and no part of an id's, which is why
            # the two are counted in their own vocabulary rather than mixed.
            chosen_keys: list = (
                named_ids or [(target_player_index, index) for index in indices]
            )
            if len(chosen_keys) != required:
                return (
                    f"{card.name} needs {required} target"
                    + ("s" if required != 1 else "")
                    + f", not {len(chosen_keys)}"
                )
            if spec.get("distinct_targets") and len(set(chosen_keys)) != required:
                # The printed "another" (CR 601.2c): two instances of the word
                # "target" may name one object *unless* something forbids it,
                # and this sentence does. Refused at the announcement rather
                # than deduplicated at resolution, which would quietly destroy
                # fewer permanents than the caster paid for.
                return f"{card.name} needs {required} different targets"
        # CR 601.2c's count for the *other* shape that has one: a spell whose
        # X is fixed at the announcement (Reap). Above the graveyard branch
        # rather than inside it, because what bounds the announcement is the
        # clause and not the zone the targets sit in — a card printing the same
        # tail over battlefield targets is gated here for free. Without this the
        # spell compiles, reports supported, and lets the caster name as many
        # cards as they like: the resolution clamps the list it *acts* on to X
        # and nothing ever says the announcement was illegal, which is an
        # ability that works more often than the card allows.
        announced = self.announced_cast_x(caster_index, card, mode_index=mode_index)
        if announced is not None:
            named_count = len(named_ids) if named_ids else len(indices)
            if named_count > announced:
                return (
                    f"{card.name} has {announced} target"
                    + ("s" if announced != 1 else "")
                    + f", not {named_count}"
                )
        if spec.get("kind") == GRAVEYARD_TARGET_KIND:
            # A named graveyard slot, checked against the ``graveyard``-kind
            # entries the same enumeration offers the picker — the one zone
            # where the per-kind arms in ``_validate_cast_targets`` cannot be
            # relied on, because they key on the *primary* instruction kind and
            # a spell whose graveyard targeting sits inside a ``sequence``
            # (Fungal Rebirth, Experimental Overload) reaches no arm at all: an
            # announcement naming an opponent's pile was accepted and
            # ``graveyard_target_seat`` then silently re-pointed it at the
            # caster's own. Same seat semantics as the activation twin above —
            # a bare index carries no seat, so a named seat narrows the
            # comparison and an unnamed one is legal on any pile the
            # enumeration offers. Ids are not read here: a card in a graveyard
            # is not a permanent (CR 115.2) and has no ``permanent_id``.
            if not indices:
                # CR 601.2c gates what was *named*. A cast that owed a card
                # and named none has had the picker's first one named for it
                # by now (``bare_announcements.default_cast_target``), so
                # nothing named here is an announcement that owes nothing.
                return None
            repeated = self._repeated_target_refusal(
                card, spec, [], indices, target_player_index
            )
            if repeated is not None:
                return repeated
            unnamed_pile = _unnamed_single_pile_refusal(
                card, spec, target_player_index
            )
            if unnamed_pile is not None:
                return unnamed_pile
            valid = self._enumerate_targets(
                caster_index, card, spec, for_cast=True, mode_index=mode_index,
            )
            legal_slots = {
                (t["seat"], t["index"]) for t in valid
                if t.get("kind") == "graveyard" and t.get("index") is not None
            }
            seats = (
                [target_player_index] if target_player_index is not None
                else list(range(len(self.players)))
            )
            for index in indices:
                if not any((seat, index) in legal_slots for seat in seats):
                    return f"no valid target for {card.name}"
            return None
        # A named **player**, and each entry of a divided list — the two
        # channels that carry a target and were compared with nothing.
        seat_refusal = self._cast_player_target_refusal(
            caster_index, card, program, spec,
            target_player_index=target_player_index,
            named_object=bool(named_ids or indices) or target_stack_item is not None,
            divided_targets=divided_targets,
            optional_cost_payments=optional_cost_payments,
            mode_index=mode_index, x_value=x_value,
        )
        if seat_refusal is not None:
            return seat_refusal
        if not named_ids and not indices:
            return None
        repeated = self._repeated_target_refusal(card, spec, named_ids, indices,
                                                 target_player_index)
        if repeated is not None:
            return repeated
        legal = self._described_cast_target_slots(
            caster_index, card, spec,
            optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
        refused = f"no valid target for {card.name}"
        chosen: list = []
        for permanent_id in named_ids:
            target = self.permanent_by_id(permanent_id)
            if target is None:
                return refused
            slot = (self.controller_index_of(target), self.battlefield_index_of(target))
            if slot not in legal:
                return refused
            chosen.append(target)
        if spec.get("same_controller") and len(chosen) > 1:
            # "Choose two target creatures **controlled by the same opponent**."
            # (Retribution, CR 601.2c.) A relation between the targets, so it
            # cannot be part of the per-candidate enumeration above — that one
            # answers "is each of these a legal target", and two creatures each
            # controlled by a *different* opponent both pass it. Asked here,
            # over the whole announcement, and only where the caster named more
            # than one: a single named target trivially shares a controller
            # with itself and refusing on a half-made announcement would refuse
            # a legal cast.
            seats = {self.controller_index_of(perm) for perm in chosen}
            if len(seats) != 1 or None in seats:
                return refused
        if named_ids:
            # Ids are the precise answer; an index beside them is the same
            # choice said twice, and re-checking it would ask about whatever
            # now sits in that slot.
            return None
        seats = (
            [target_player_index] if target_player_index is not None
            else list(range(len(self.players)))
        )
        for index in indices:
            if not any((seat, index) in legal for seat in seats):
                return refused
        return None

    def _cast_player_target_refusal(
        self, caster_index: int, card: CardDefinition, program, spec: dict, *,
        target_player_index, named_object: bool, divided_targets,
        optional_cost_payments: dict | None, mode_index: int | None,
        x_value: int | None,
    ) -> str | None:
        """CR 601.2c for the targets a cast names **without an id**: a player,
        and each entry of a CR 601.2d division. Returns the refusal, or None.

        :meth:`cast_target_refusal`'s other half, and the same comparison — the
        named target against the list ``_enumerate_targets`` hands the picker —
        so every narrowing a player phrase can print is enforced by being in
        that list rather than by being listed here: "target **opponent**"
        (CR 102.2), a player with shroud (CR 702.18a), one who has left the
        game (CR 800.4a), "who attacked this turn", a compared seat.

        **When is the seat a target?** ``target_player_index`` is a chosen
        player in one arrangement and the battlefield a permanent sits on in
        another, and the announcement says which:

        * a spec that is a **player and nothing else** — the seat is the
          target, whatever was sent beside it;
        * "**any target**" / "player or planeswalker" — the seat is the target
          only when no object was named (the ids decide, exactly as
          ``stack_targets._read`` reads the stack item this becomes). With an
          object beside it the seat is a battlefield, and the permanent is
          checked against its slot by the caller;
        * a **divided** spell — each entry of the division is its own target,
          a face where its slot is None, and the scalar seat beside the list
          names nothing. Without a list, a seat alone is the lawful one-target
          announcement ``casting._named_divided_targets`` counts;
        * a spec that offers no player at all (``spec_offers_a_player``: "…among
          any number of target **creatures**") — the seat is the one every cast
          carries, and is not compared;
        * a **roles** spec (Donate's player beside its permanent) never reaches
          here: the caller hands the whole announcement to
          ``_validate_cast_targets``, which walks it role by role through the
          same enumeration.

        **A cast that names nobody is held to the same list.** A spell that
        owes a target and names none resolved on the default seat
        (``_resolve_card``: the opposing one) whether or not the picker
        offered it — 101 of 119 bare casts resolved on a player with shroud —
        and this gate then refused such a cast. It is answered one step
        earlier now: the cast path names the picker's first entry in standing
        order for it (``bare_announcements.default_cast_target``), so the
        seat that reaches this gate is one the list holds, and the refusal
        below stands only for an announcement that path does not default (a
        counted or several-role one). An announcement that may name nobody
        ("up to one target player") owes nothing and is not asked.
        """
        refused = f"no valid target for {card.name}"
        offered: list | None = None

        def legal() -> list:
            nonlocal offered
            if offered is None:
                offered = self._enumerate_targets(
                    caster_index, card, spec, for_cast=True,
                    optional_cost_payments=optional_cost_payments,
                    mode_index=mode_index,
                )
            return offered

        if divided_targets and spec.get("kind") == "divided":
            faces = {t["seat"] for t in legal() if t.get("kind") == "player"}
            slots = {
                (t["seat"], t["index"]) for t in legal()
                if t.get("kind") == "permanent"
            }
            for entry in divided_targets:
                seat, index, _share = divided_entry(entry)
                if index is None:
                    if seat not in faces:
                        return refused
                elif (seat, index) not in slots:
                    return refused
            return None
        if not spec_offers_a_player(spec) or spec_is_a_cost(spec):
            return None
        if any(spec.get(flag) for flag in ("source_of_choice", "optional")):
            # CR 609.7a's chosen source and Clone's optional copy are picked,
            # not targeted (``stack_targets._UNTARGETED_SPEC_FLAGS``).
            return None
        if named_object and spec.get("kind") != "player":
            return None
        faces = {t["seat"] for t in legal() if t.get("kind") == "player"}
        if isinstance(target_player_index, int) and not isinstance(
            target_player_index, bool
        ):
            return None if target_player_index in faces else refused
        if named_object:
            return None
        if cast_target_obligation(
            card, program, optional_cost_payments=optional_cost_payments,
            x_value=x_value, mode_index=mode_index,
        ) is None:
            return None
        standing = self._spell_default_seat(caster_index)
        if not 0 <= standing < len(self.players) or standing in faces:
            return None
        return (
            f"{card.name} has to name its target: {self.players[standing].name} "
            f"can't be chosen (CR 601.2c)"
        )

    def cast_target_count_refusal(
        self, caster_index: int, card: CardDefinition, *,
        target_player_index=None, target_permanent_index=None,
        target_permanent_ids=None, x_value: int | None = None,
        optional_cost_payments: dict | None = None,
        mode_index: int | None = None,
    ) -> str | None:
        """CR 601.2c: a spell printing an **exact** number of targets names
        exactly that many. Returns the refusal, or None.

        "The player announces their choice of an appropriate object or player
        for **each** target the spell requires." A printed "two" requires two;
        "up to two" and "any number of" make fewer legal, and those are not
        this gate's (:func:`exact_target_count` answers None for them). The
        count is the slot's own, for the mode announced (*mode_index*) and the
        kicker paid (*optional_cost_payments*, CR 702.33g).

        Asked **after X is settled** — "Tap X target creatures" is counted
        against the X the caster announced (CR 601.2b precedes CR 601.2c), so
        the cast path calls this below the X resolution rather than beside the
        other target gates, and hands it None for an X the engine merely
        inferred from the pool: a number the caster never said is not a number
        to hold their targets to.

        A cast naming **nothing** is counted like any other. That is the
        difference from a one-target spell, whose unnamed cast names the
        picker's first entry (``engine/bare_announcements.py``): which two of
        several creatures a caster who named none "meant" is not one answer
        drawn from one list, so "two target creatures" naming none is refused
        rather than defaulted — it used to resolve doing nothing, with its
        costs paid.
        """
        if card.primary_type not in ("instant", "sorcery"):
            return None
        program = compile_card_oracle(card)
        if program.modes and program.mode_chooser is not None:
            return None
        slot = cast_target_slot(
            card, program, optional_cost_payments=optional_cost_payments,
            mode_index=mode_index,
        )
        if slot is None:
            return None
        required = exact_target_count(slot[0], slot[1], x_value)
        if required is None:
            return None
        named_ids = [pid for pid in (target_permanent_ids or []) if isinstance(pid, int)]
        indices = (
            [i for i in target_permanent_index if isinstance(i, int)]
            if isinstance(target_permanent_index, list)
            else ([target_permanent_index] if isinstance(target_permanent_index, int) else [])
        )
        named = len(named_ids) if named_ids else len(indices)
        if named == required:
            return None
        return (
            f"{card.name} needs {required} target"
            + ("s" if required != 1 else "")
            + f", not {named}"
        )
