"""What a spell may be announced with (CR 601.2b-c): the picker in front of
a cast, the X its own text fixes, and the optional prices it may be cast for.

Part of the legality queries ``engine/legality.py`` opens with, and the part
the client is *handed*: :meth:`CastTargetSpecMixin.cast_target_spec` is the
whole spec a browser renders before a spell is cast — the target kind, every
legal target the enumerator offers for it, the picker of a cost that names a
permanent, an entry trigger's own list for a permanent spell — and
:meth:`CastTargetSpecMixin.cast_cost_offers` is every optional price CR 601.2b
lets the caster announce, with what each costs and how often it is payable.

What is *refused* once something is named is the other half and lives one
module over (``engine/legality_cast_gates.py``); the enumeration both halves
read is ``engine/legality_enumeration.py``. They are separate because the
offer and the refusal are asked at different moments by different callers -
the offer on every poll, the refusal once, before a cost is paid — and both
read the one enumeration, which is what keeps them agreeing.
"""

from __future__ import annotations

from .models import CardDefinition, Permanent
from .cast_costs import (
    buyback_cost,
    cast_announces_x,
    costs_charged_from,
    kicker_costs,
)
from .divided_damage import divided_entry
from .faces import is_multi_face
from .cost_x_definitions import (
    caps_cast_x,
    cast_x_ceiling,
    cast_x_value,
    defines_cast_x,
)
from .oracle import compile_card_oracle
from .mana_payment import (
    mana_cost_from_symbols,
    plan_payment,
    total_pips,
    untapped_mana_lands,
)
from .oracle_types import cost_target_count
from .target_requirements import (
    announcement_refusal,
    cast_is_bound,
    narrow_offer,
    requirements_binding,
)
from .targeting import (
    ROLES_TARGET_KIND,
    cast_announced_entry_trigger,
    derive_cast_spec,
)
from .legality import _cast_picker_is_a_target
from .legality_enumeration import _cast_from_graveyard_slot


class CastTargetSpecMixin:
    """What a spell may be announced with: its picker, its X and its
    optional costs. Composed onto ``Game`` beside ``LegalityMixin``."""

    # -- Targeting ---------------------------------------------------------

    def announced_cast_x(
        self, caster_index: int, card: CardDefinition, *,
        mode_index: int | None = None,
    ) -> int | None:
        """CR 601.2b: the X this spell's own where-clause fixes **at the
        announcement**, or None when it defines none.

        "Return up to X target cards from your graveyard to your hand, where X
        is the number of black permanents target opponent controls **as you cast
        this spell**." (Reap.) Three callers ask, all of them before any cost is
        paid and all of them about the same board: the picker (so the browser
        offers at most X cards), :meth:`cast_target_refusal` (so an announcement
        naming more than X is refused, CR 601.2c), and the cast path (so the
        number is stamped on the stack item and the resolution reads it rather
        than counting again). One function, because three readings of one count
        are three chances for the picker to offer what the gate refuses.

        Evaluated through ``count_from_payload`` — the *same* evaluator the
        resolution uses — rather than through a cast-time arithmetic of its own.
        That is the whole point: CR 601.2c says the number does not change once
        determined, and the only way to be sure the frozen number is the one the
        clause means is for both moments to ask one function. What differs is
        the moment, which is what the caller supplies.

        **No seat is taken from the caller**, and that is a rule rather than an
        omission. The cast wire carries one ``target_player_index``, and for a
        spell whose targets sit in a graveyard that field already means *which
        pile* — so reading it here would count a board the caster never named,
        and differently in the picker (which has no such field) than in the gate.
        ``count_from_payload`` resolves the seat itself (CR 102.3: a player is
        never their own opponent, so the fallback is the first living one),
        which in a two-player game is the only announcement CR 601.2c permits;
        the lowering refuses any scope that would need an answer this cannot
        give.
        """
        from .game_types import OracleExecutionContext
        from .handlers._common import count_from_payload
        from .targeting import cast_time_count_spec

        spec = cast_time_count_spec(
            compile_card_oracle(card), mode_index=mode_index
        )
        if spec is None:
            return None
        caster = self.players[caster_index]
        context = OracleExecutionContext(caster=caster, target=caster, card=card)
        return max(0, int(count_from_payload(self, context, spec)))

    def _size_conditional_division(
        self, caster_index: int, card: CardDefinition, spec: dict
    ) -> None:
        """Make a divided spec's ``division_total`` the amount of the arm the
        board selects **now**, where the card prints two.

        "Shower of Coals deals 2 damage to each of up to three targets. …
        deals 4 damage to each of those permanents and/or players instead if
        there are seven or more cards in your graveyard." One list, two
        amounts, and the amount is settled as the spell resolves (CR 608.2h).
        The card-level spec carries the replacing arm's (``derive_cast_spec``
        has no game to ask), so a picker and the AI's "how much does each
        target take" were told 4 over a graveyard of none.

        Asked through the resolution's own evaluator with the caster's game as
        it stands — the answer a spell cast and resolved now would get. It can
        still change before the spell resolves, which is the rule; what this
        stops is the spec naming a number the present board contradicts.

        A condition settled at the cast (``was_kicked``) is not this:
        ``divided_damage.conditional_division`` hands back only the
        resolution-time kind, and the kicker's arm is already chosen by the
        announcement the spec was derived for.
        """
        from .divided_damage import conditional_division
        from .game_types import OracleExecutionContext
        from .handlers.control_flow import evaluate_condition

        arms = conditional_division(compile_card_oracle(card).instructions)
        if arms is None:
            return
        condition, replacing, base = arms
        caster = self.players[caster_index]
        holds = evaluate_condition(
            self,
            OracleExecutionContext(caster=caster, target=caster, card=card),
            condition,
        )
        amount = (replacing if holds else base).payload.get("amount")
        if isinstance(amount, int) and not isinstance(amount, bool):
            spec["division_total"] = amount

    def cast_target_spec(
        self,
        caster_index: int,
        card: CardDefinition,
        *,
        from_zone: str = "hand",
        spell_hand_index: int | None = None,
        optional_cost_payments: dict[str, int] | None = None,
        mode_index: int | None = None,
        requirements: bool = True,
    ) -> dict:
        """Target spec for casting ``card`` from ``caster_index``'s *from_zone*:
        the target kind plus every legal target, enumerated and gated through the
        engine's own cast-target validation so the UI offers exactly what would
        resolve.

        ``mode_index`` asks for **one mode** of a "Choose one —" spell: the
        whole spec that mode would have were it a spell of its own — kind,
        narrowing flags, roles, the several-target count, the chosen-source
        list — enumerated through the same per-candidate probe the cast gate
        runs for that mode (``_enumerate_targets(mode_index=)``). Without it a
        modal card answers ``"modal"``, as it always has: there is a choice to
        make before any target. ``web/serialization._serialize_modes`` sends
        one of these per mode, which replaced a per-kind table of its own whose
        fall-through answered "player" — so what the browser offers for a mode
        and what :meth:`cast_target_refusal` accepts for it are one list.

        ``from_zone`` is the zone the cast would leave, because a printed
        additional cost may name one (Demonic Embrace's graveyard price) and the
        picker has to charge what the payment path will charge — the same test
        ``queue_from_hand`` makes.

        ``optional_cost_payments`` is CR 601.2b's answer **so far** — the offers
        the caster has already accepted. It is what makes this spec re-askable:
        the offer ceilings below are computed against it, and so is CR 601.2c's
        target count for the one shape whose count a payment decides (Primitive
        Justice destroys one artifact, plus another for each {1}{R} and each
        {1}{G} paid). ``spell_hand_index`` is which copy is being cast, needed
        for the same reason CR 601.2a is: a spell cannot be exiled to pay for
        itself, and a second copy in hand can.

        **The list is what this caster may announce now**, so a requirement an
        opponent's permanent prints about that announcement is already in it
        ("…that player must choose at least one Flagbearer on the battlefield if
        able", ``engine/target_requirements.py``): a one-target spell that
        could name a Flagbearer is offered Flagbearers alone, and a spell with
        several slots keeps its list and carries ``required_targets``.
        ``requirements=False`` is the same spec without that — every *legal*
        target — which is what the announcement gate measures "if able"
        against (:meth:`cast_target_requirement_refusal`)."""
        # CR 709.3: a split card is not a spell until a half is chosen, and each
        # half has its own spec — asked of the half (`faces.face_cards`), which
        # is the card the cast path and the serializer both hand this method.
        # The whole card answers "faces" for the reason a modal card answers
        # "modal" below: there is a choice to make before any target.
        if is_multi_face(card):
            return {"kind": "faces", "requires_target": False, "valid_targets": []}
        # Modal "Choose one —" spells choose a mode first; each mode carries its
        # own target spec (filled in by the web layer per mode), so report "modal"
        # and let the UI run its mode-choice flow rather than enumerating here.
        program = compile_card_oracle(card)
        if len(program.modes) >= 2 and mode_index is None:
            return {"kind": "modal", "requires_target": False, "valid_targets": []}
        # The compiled program answers in full — the kind *and* the flags that
        # narrow the picker (own_only, stack filters, sacrifice_cost, ...).
        # There is no text cascade behind this any more: a program that
        # describes no cast-time choice means the spell makes none.
        spec = derive_cast_spec(
            card, program, from_zone=from_zone,
            # CR 601.2b's answer so far, for the one cost kind that is an offer
            # rather than a price: a declined buyback asks the caster to name
            # nothing, and a taken one needs the picker its price implies.
            #
            # **An answer not yet given is "nothing taken"**, not "unknown":
            # this is the spec a player is shown, and CR 702.33g gives a
            # kicked-only part's targets to a spell that was kicked and to no
            # other. So a card looked at before any offer is answered is read
            # as the unkicked cast it so far is -- Benalish Emissary asks for no
            # land -- and the offer prompt re-asks with the kicker taken.
            optional_cost_payments=optional_cost_payments or {},
            mode_index=mode_index,
        ) or {"kind": "none"}
        spec["requires_target"] = spec["kind"] != "none"
        if spec.get("kind") == "divided" and mode_index is None:
            self._size_conditional_division(caster_index, card, spec)
        # CR 107.3c: a spell that defines its own X takes the announcement away
        # from the caster, so the picker must not ask for one — and a divided
        # spell's caster needs the number *before* announcing the division
        # (CR 601.2d), which is exactly what a browser that had asked for X
        # would have got wrong. Answered here rather than in the browser because
        # the definition counts a graveyard, which only the game can read.
        if defines_cast_x(card.oracle_text):
            defined = cast_x_value(self, caster_index, card.oracle_text)
            if defined is not None:
                spec["defined_x"] = defined
        # CR 601.2b's bound, the other half of the same question: the caster
        # still announces X and this is the largest legal answer (Winter's
        # Chill). Reported here for ``defined_x``'s reason — the number counts
        # a board only the game can read — so the picker offers what the cast
        # path would accept rather than a range it will then refuse.
        if caps_cast_x(card.oracle_text):
            bound = cast_x_ceiling(self, caster_index, card.oracle_text)
            spec["max_x"] = 0 if bound is None else bound[0]
        # CR 601.2b's *third* answer, and the one that also sizes the target
        # list: a where-clause counted "as you cast this spell" (Reap). Like
        # ``defined_x`` above it takes the announcement away from the caster, so
        # it is reported the same way and the browser asks for no X — and
        # because CR 601.2c fixes the number of targets from it, the count
        # becomes an ordinary ``max_targets`` here. ``x_targets`` is dropped in
        # the same breath: that flag means "however many the announced X pays
        # for", which is a question with an answer now.
        announced = self.announced_cast_x(caster_index, card, mode_index=mode_index)
        if announced is not None:
            spec["defined_x"] = announced
            spec.pop("x_targets", None)
            spec["max_targets"] = announced
        # CR 107.3a's *other three* places an X can live. The browser asked only
        # the mana-cost string, so Fire Covenant ({1}{B}{R}, "pay X life") and
        # Infernal Harvest ({1}{B}, "return X Swamps") were offered no X box at
        # all and cast at the 0 an unmade CR 107.3a announcement reads as here
        # -- legal and useless. Reported as a flag
        # rather than left to a substring probe for the reason `defined_x` is:
        # what a card's costs say is the compiler's answer, not the client's.
        # CR 601.2b's other announcement: a printed additional cost that makes
        # the caster **choose a creature type** (Caller of the Hunt). Reported
        # on the spec for ``announces_x``'s reason exactly — what a card's costs
        # say is the compiler's answer, not the client's — and with the catalog
        # and the default beside it, because neither is something a browser can
        # derive: CR 205.3m's list is ingested data and the default counts a
        # board only the game can read.
        #
        # Without this the picker asks nothing, the cast takes the default, and
        # a human seat silently gets the engine's guess at the one choice the
        # card is entirely about.
        if any(cost.choose_creature_type for cost in costs_charged_from(card, from_zone)):
            from .grammar.vocabulary import CREATURE_TYPES

            spec["announces_creature_type"] = True
            spec["creature_types"] = sorted(CREATURE_TYPES)
            spec["default_creature_type"] = self._default_cast_creature_type(
                caster_index, card
            )
        if cast_announces_x(
            card, from_zone=from_zone, taken=optional_cost_payments
        ):
            spec["announces_x"] = True
            # And the ceiling that goes with it, which the mana pool cannot
            # supply because this X is not paid in mana: a life total (CR 119.4)
            # or a board of Swamps (CR 601.2h). The same numbers
            # `_unpayable_additional_cost` refuses above, so the picker offers
            # exactly what the cast would accept.
            bound = self._additional_cost_x_ceiling(
                caster_index, card, from_zone=from_zone,
                spell_hand_index=(
                    spell_hand_index if from_zone == "hand" else None
                ),
                taken=optional_cost_payments,
            )
            if bound is not None:
                spec["max_x"] = (
                    bound if spec.get("max_x") is None
                    else min(int(spec["max_x"]), bound)
                )
            # …and the **floor**, for the one cost that prints one: "choose a
            # number between 1 and 3" may not announce 0. ``max_x`` above is
            # that range's other end (`_additional_cost_x_ceiling`), so the two
            # keys are the card's own range and ``number_refusal`` is what
            # refuses anything outside it. Absent when the floor is 0, which is
            # where every X box already starts.
            floor = max(
                (
                    cost.choose_number[0]
                    for cost in costs_charged_from(card, from_zone)
                    if cost.choose_number is not None
                ),
                default=0,
            )
            if floor > 0:
                spec["min_x"] = floor
        # "This spell costs {1} more to cast for each target beyond the first."
        # (Fireball; Phyrexian Purge charges life.) CR 601.2f prices the spell
        # by the targets CR 601.2c chose, and the picker sizes its X box from
        # the same arithmetic — which it did by assuming Fireball's sentence of
        # every divided spell, so Captain's Maneuver's two targets were taxed a
        # mana its card does not charge and its X stopped one short of what the
        # pool could pay. The table the cast path charges from
        # (``self_cost_modifiers.self_per_target_tax``), reported rather than
        # mirrored; absent where no such line is printed.
        from .self_cost_modifiers import self_per_target_tax

        per_target = self_per_target_tax(card.oracle_text or "")
        if per_target is not None:
            spec["per_target_tax"] = {
                "amount": per_target.amount,
                "life": per_target.life,
                "beyond_first": per_target.beyond_first,
            }
        # CR 601.2b's *optional* prices, and how many times each is payable
        # against the answer so far. The picker had no shape for an offer at
        # all — it modelled a cost the caster will certainly pay — so every card
        # printing one was castable at its printed default and at no other
        # price.
        offers = self.cast_cost_offers(
            caster_index, card, from_zone=from_zone,
            spell_hand_index=spell_hand_index, taken=optional_cost_payments,
            # CR 903.8's tax is a cost increase like any other, and CR 118.9d
            # applies it to an alternative cost: the offer's ``payable`` is
            # told what this zone adds.
            extra_generic=(
                self.commander_tax(caster_index, card)
                if from_zone == "command" else 0
            ),
        )
        if offers:
            spec["cost_offers"] = offers
        # CR 601.2c's count, once CR 601.2b has been answered. The arithmetic
        # lives in ``oracle_types.cost_target_count`` because the grammar writes
        # the description, this turns it into a picker size and
        # ``_validate_cast_targets`` gates the announcement against it — three
        # readers of one pair of dict keys, which is why none of them owns the
        # sum. Emitted as an ordinary ``max_targets`` so the several-target
        # picker has to know nothing about costs.
        sized = cost_target_count(spec.get("cost_targets"), optional_cost_payments)
        if sized is not None and sized > 1:
            spec["max_targets"] = sized
        if spec["kind"] == ROLES_TARGET_KIND:
            # A spell whose targets are of *different kinds*, chosen in
            # dependency order (CR 601.2c). ``valid_targets`` is role 0's list —
            # the shape every caller downstream already reads, so "does this
            # spell have a legal target at all?" keeps working — and each entry
            # carries under ``next`` the targets the later roles would then
            # allow. One walk, so what the browser offers and what
            # ``_validate_cast_targets`` accepts come from the same call.
            spec["valid_targets"] = self._role_target_walk(
                caster_index, card, spec, (), for_cast=True
            )
            # …and CR 609.7a's source, for the one roles spell that also asks
            # for one (Kor Chant). This return is early by design — the walk
            # replaces `_enumerate_targets` — so the shared tail below is out of
            # reach and the source list has to be attached here too.
            self._attach_chosen_source_targets(caster_index, card, spec)
            # …and the cost picker's candidates, for the same reason. A kicked
            # Falling Timber is the first roles spell that also pays with a
            # permanent ("Kicker—Sacrifice a land"): without this the picker
            # described a land to give up and offered none to choose from.
            if spec.get("cost_spec"):
                cost_spec = dict(spec["cost_spec"])
                cost_spec["valid_targets"] = self._enumerate_targets(
                    caster_index, card, cost_spec, for_cast=True,
                )
                spec["cost_spec"] = cost_spec
            return self._under_target_requirements(
                caster_index, card, spec, requirements, mode_index
            )
        # **A permanent spell's picker is its entry trigger's own list.** The
        # target named here is the one the trigger will choose as it is put on
        # the stack (CR 603.3d), so what may be named is what that choice
        # would accept — see :meth:`entry_trigger_cast_targets`. None for every
        # other cast, which enumerates as it always has.
        trigger_targets = self.entry_trigger_cast_targets(
            caster_index, card, optional_cost_payments=optional_cost_payments or {},
        )
        if trigger_targets is not None:
            # …less the card being cast, when the cast is out of the caster's
            # own graveyard (CR 601.2a: it is on the stack before anything is
            # named) — the exclusion the spell's own enumeration makes, asked
            # of the trigger's list (Gravedigger cast from a graveyard).
            leaving = _cast_from_graveyard_slot(
                spec, self.players[caster_index].graveyard, card,
            )
            if leaving is not None:
                trigger_targets = [
                    entry for entry in trigger_targets
                    if not (
                        entry.get("kind") == "graveyard"
                        and entry.get("seat") == caster_index
                        and entry.get("index") == leaving
                    )
                ]
        spec["valid_targets"] = (
            trigger_targets if trigger_targets is not None
            else self._enumerate_targets(
                caster_index, card, spec, for_cast=True,
                # The same answer the spec above was derived under (CR 702.33g).
                optional_cost_payments=optional_cost_payments or {},
                # …and the same mode (CR 601.2b).
                mode_index=mode_index,
            )
        )
        # Demonic Embrace, Goblin Grenade, Soul Exchange: a spell with a target
        # *and* a choosable cost carries two pickers, each enumerating its own
        # candidates — the cost over the caster's own cards with no targeting
        # legality, the target through everything above. The activation side has
        # answered this way since Dwarven Weaponsmith; the cast side used to
        # answer with the cost alone, which is how the target went unasked.
        if spec.get("cost_spec"):
            cost_spec = dict(spec["cost_spec"])
            cost_spec["valid_targets"] = self._enumerate_targets(
                caster_index, card, cost_spec, for_cast=True,
            )
            spec["cost_spec"] = cost_spec
        # "Any number of target …" (Drafna's Restoration) prints no maximum, so
        # the cap is however many legal targets there are — a number that exists
        # here and nowhere earlier. Filled in as an ordinary `max_targets` so
        # every reader downstream sees the shape it already handles.
        if spec.pop("unbounded_targets", False):
            spec["max_targets"] = len(spec["valid_targets"])
        # "The next time **a source of your choice** would deal damage to any
        # target this turn…" (Honorable Passage). A cast that announces a
        # source as well as a target, which is the activation path's Jade
        # Monolith shape one announcement step over.
        self._attach_chosen_source_targets(caster_index, card, spec)
        return self._under_target_requirements(
            caster_index, card, spec, requirements, mode_index
        )

    def _under_target_requirements(
        self, caster_index: int, card: CardDefinition, spec: dict, wanted: bool,
        mode_index: int | None,
    ) -> dict:
        """*spec* as the cast picker presents it under the target
        requirements in force (``target_requirements.narrow_offer``).

        Asked only of a spell that **targets as it is cast** — an instant, a
        sorcery or an Aura (CR 115.1a/b). Any other permanent spell's picker
        is its entry trigger's, and a triggered ability "doesn't have to
        target a Flagbearer" (ruling, 2016-06-08).
        """
        if not wanted or not _cast_picker_is_a_target(card, mode_index):
            return spec
        return narrow_offer(self, caster_index, spec)

    def cast_target_requirement_refusal(
        self, caster_index: int, card: CardDefinition, *,
        announcements, divided_targets=None, from_zone: str = "hand",
        optional_cost_payments: dict | None = None,
    ) -> str | None:
        """CR 601.2c under a requirement an opponent's permanent prints: why
        this cast's **whole announcement** is not one the caster may make, or
        None.

        "While an opponent is choosing targets as part of casting a spell they
        control…, that player must choose at least one Flagbearer on the
        battlefield if able." A rule about the announcement rather than about
        any one target, which is why it is a gate of its own beside
        :meth:`cast_target_refusal` and not a narrowing inside
        ``_enumerate_targets``: that list is also what the resolution re-asks
        (CR 608.2b) and what a retarget and a trigger choose from, none of
        which the card binds.

        *announcements* is ``cast_announcement._mode_announcements``' rows — one per
        announced mode — and *divided_targets* CR 601.2d's list; between them
        they are everything the cast named. "If able" is measured against the
        picker's own un-narrowed list for each row, so a Flagbearer the spell
        could not legally target binds nothing. An opponent-chosen mode
        (CR 700.2e) names its targets after the cast and is not asked here.
        """
        if not cast_is_bound(card) or not requirements_binding(self, caster_index):
            return None
        program = compile_card_oracle(card)
        if program.modes and program.mode_chooser is not None:
            return None
        specs: list[dict] = []
        named: set = set()
        for mode_index, seat, slot, ids, _stack_item in announcements:
            if mode_index is None and program.modes:
                # A cast naming no mode is the mode-0 cast it resolves as.
                mode_index = 0
            if not _cast_picker_is_a_target(card, mode_index):
                continue
            specs.append(self.cast_target_spec(
                caster_index, card, from_zone=from_zone,
                optional_cost_payments=optional_cost_payments,
                mode_index=mode_index, requirements=False,
            ))
            listed = [pid for pid in (ids or ()) if isinstance(pid, int)]
            if listed:
                named.update(listed)
                continue
            # A slot beside a seat — the legacy spelling, and the only one a
            # "choose one or more" mode has. With no seat the cast resolves on
            # its default one, so that is the battlefield the slot counts into.
            board = (
                seat if isinstance(seat, int)
                else self._spell_default_seat(caster_index)
            )
            for index in (slot if isinstance(slot, list) else [slot]):
                if isinstance(index, int) and not isinstance(index, bool):
                    permanent = self.permanent_at(board, index)
                    if permanent is not None:
                        named.add(permanent.permanent_id)
        for entry in divided_targets or ():
            seat, index, _share = divided_entry(entry)
            if index is None:
                continue
            permanent = self.permanent_at(seat, index)
            if permanent is not None:
                named.add(permanent.permanent_id)
        return announcement_refusal(self, caster_index, card.name, specs, named)

    def entry_trigger_cast_targets(
        self, caster_index: int, card: CardDefinition, *,
        optional_cost_payments: dict | None = None,
    ) -> "list[dict] | None":
        """What a cast of the permanent *card* may name for its entry trigger:
        the targets **that trigger could choose for itself**, or None when the
        cast names no trigger's target (or the trigger makes no choice the
        picker could list).

        This engine names an entry trigger's target as the permanent is cast,
        and the picker for it used to be ``_enumerate_targets(for_cast=True)``
        — a *spell's* enumeration, whose per-candidate legality is
        ``_validate_cast_targets``, which returns "valid" for every permanent
        spell that is not an Aura. So the list was every permanent of the right
        type and nothing else was asked: protection from the permanent's
        colour or from creatures (CR 702.16b), shroud and hexproof, and every
        narrowing the trigger's own instruction carries ("target **red or
        green** creature", Hunting Drake) were all offered. 104 entries across
        44 shipped permanents on one board.

        The list is ``_trigger_target_candidates`` — the one
        ``_choose_trigger_targets`` offers when the same permanent enters
        without being cast, and the one ``cast_announcement_fault`` holds the
        announcement to as the trigger is put on the stack — asked of the
        trigger as it will exist. Its source is not on the battlefield yet, so
        it is described by a **prospective** permanent: the card as printed,
        controlled by nobody, with an id no object has. That is enough for
        every question the enumerator asks of an ability's source (which
        qualities protection is measured against, whether it is the excluded
        "another", what it has dealt damage to), and whatever the real
        permanent turns out to differ in — a colour chosen as it enters — is
        the push's to catch, where the object exists.
        """
        slot = cast_announced_entry_trigger(
            card, compile_card_oracle(card),
            optional_cost_payments=optional_cost_payments,
        )
        if slot is None:
            return None
        from .game_types import StackItem

        ability, instruction = slot
        prospective = StackItem(
            card, caster_index, None, None, None,
            ability_instruction=instruction,
            ability_effect_kind=ability.effect_kind,
            ability_text=ability.source_line,
            source_permanent=Permanent(card=card, permanent_id=-1, timestamp=0),
        )
        offer = self._trigger_target_candidates(prospective, announced=True)
        return None if offer is None else offer[2]

    def cast_cost_offers(
        self,
        caster_index: int,
        card: CardDefinition,
        *,
        from_zone: str = "hand",
        spell_hand_index: int | None = None,
        taken: dict[str, int] | None = None,
        extra_generic: int = 0,
    ) -> list[dict]:
        """Every *optional* price CR 601.2b lets the caster announce for *card*,
        with what each one costs and how many times it is payable.

        *extra_generic* is what the zone adds to this cast's cost (CR 903.8's
        commander tax), for the one offer whose ``payable`` is a promise about
        the whole cast: the alternative cost's (see below).

        The two optional cost kinds this engine has grown, described in one
        vocabulary because the browser asks one question about them ("what are
        you paying for this?"):

        * **CR 118.9's alternative cost** -- "You may pay 1 life and exile a blue
          card from your hand rather than pay this spell's mana cost." Taken or
          not; the exile half names a card, so the cards that answer it are
          enumerated here through ``_alternative_cost_payers``, the same list the
          payment picks from.
        * **CR 601.2b's optional additional mana** -- "you may pay {1}{R} and/or
          {1}{G} any number of times." Taken any number of times, *independently*
          per offer (Primitive Justice prints two), which is why ``times`` is a
          map and not a count.

        ``taken`` is the answer so far, and the ceilings are computed against it:
        raising one offer spends mana the others can no longer have. A client
        that re-asks after each click therefore gets a ceiling that is true
        jointly, rather than three standalone maxima that cannot all be taken.

        **The ceiling is computed from the pool and the board**, through
        ``plan_payment`` -- the same matching the payment itself runs, so an
        offer this shows as payable is one the cast will accept. It reads the
        *printed* mana cost: a CR 601.2f increase in force would make the number
        optimistic, and an optimistic offer is refused by the payment with
        nothing spent, where a pessimistic one silently withholds a price the
        player could afford.
        """
        caster = self.players[caster_index]
        answered = {str(key): int(value) for key, value in (taken or {}).items()}
        offers: list[dict] = []

        # Printed **and** granted (Dream Halls' board-wide offer), through the
        # one reader the announcement's check and the CR 601.2h gate also ask:
        # an offer this picker could not describe is a price no client can take,
        # which is the whole of what the alternative-cost prompt exists for.
        for cost in self.applicable_alternative_costs(caster_index, card):
            entry: dict = {
                "kind": "alternative",
                "label": cost.describe(),
                "payable": self._unpayable_alternative_cost(
                    caster_index, card, cost, spell_hand_index=spell_hand_index,
                ) is None,
            }
            # CR 118.9d: "any additional costs, cost increases, and cost
            # reductions that affect that spell are applied to that alternative
            # cost." So a pitched card and a life are not the whole price under
            # Sphere of Resistance — the {1} is owed beside them, and an offer
            # that says "payable" over a board that cannot make it is a cast
            # the payment refuses (and the reason the castable highlight, which
            # falls back to this flag, glowed over it). Priced by the one
            # reader the AI plans the same announcement with, and asked of the
            # pool plus the untapped lands as every other ceiling here is.
            # ``mana_owed`` tells the prompt what to float.
            if self.enforce_mana_costs:
                from .board_payment import board_can_pay
                from .mana_payment import mana_cost_label
                from .restricted_mana import CAST, PaymentPurpose

                owed = self.alternative_cost_mana(
                    caster_index, card, cost, extra_generic=extra_generic,
                )
                if any(owed.values()):
                    entry["mana_owed"] = mana_cost_label(owed)
                    entry["payable"] = entry["payable"] and board_can_pay(
                        self, caster_index, owed,
                        purpose=PaymentPurpose(CAST, card=card),
                    )
            if (
                cost.exile_from_hand is not None
                or cost.discard_from_hand is not None
            ):
                payers = self._alternative_cost_payers(
                    caster_index, cost, spell_hand_index=spell_hand_index,
                    spell=card,
                )
                # By hand *position*, because that is what the wire carries and
                # what CR 601.2a's withholding is expressed in: a deck repeats
                # one immutable definition per copy, so two copies of one card
                # in hand are the same Python object and only the index tells
                # the spell apart from the card paying for it.
                entry["hand_choices"] = [
                    {"index": position, "name": held.name}
                    for position, held in enumerate(caster.hand)
                    if position != spell_hand_index
                    and any(held is payer for payer in payers)
                ]
                # Which zone the chosen card goes to, so the button names it:
                # "Discard a Swamp card" (Outbreak) and Dream Halls' granted
                # discard were offered as "Exile Swamp", a price the player is
                # not paying — the card lands in the graveyard, where a spell
                # may read it back.
                entry["hand_verb"] = (
                    "exile" if cost.exile_from_hand is not None else "discard"
                )
                # "…discard an Island card **and another card**" (Foil): how
                # many further cards, and which may be them — every card but
                # the spell. The client keeps the one it chose for the Island
                # half out of this list; the engine refuses it either way.
                if cost.discard_others:
                    entry["other_discards"] = cost.discard_others
                    entry["other_hand_choices"] = [
                        {"index": position, "name": held.name}
                        for position, held in enumerate(caster.hand)
                        if position != spell_hand_index
                    ]
            # "…you may **sacrifice a creature** rather than pay this spell's
            # mana cost" (Mind Swords), "**tap an untapped creature you
            # control**" (Lashknife): a price paid with a permanent owes the
            # caster a choice of which one (CR 601.2b), and the candidates are
            # the list the CR 601.2h gate counts and the payment takes from.
            # By id, because that is what ``alternative_cost_permanent_ids``
            # carries back and what survives the board renumbering behind
            # each payment.
            permanent_payment = self.alternative_cost_permanent_payment(cost)
            if permanent_payment is not None:
                verb, count = permanent_payment
                entry["permanent_verb"] = verb
                entry["permanent_count"] = count
                entry["permanent_choices"] = [
                    {"id": perm.permanent_id, "name": perm.card.name}
                    for perm in self._additional_cost_candidates(
                        caster_index, cost, giving_up=verb
                    )
                ]
            offers.append(entry)
            # CR 118.9a: only one alternative cost may be applied, and
            # ``_resolve_alternative_cost`` refuses a card printing two rather
            # than choosing for the player. Offering both would be this picker
            # describing an announcement the engine will not accept.
            break

        # Which of these offers is the card's **buyback** (CR 702.27a), so the
        # prompt can name the price rather than showing a bare "{3}" or a bare
        # "sacrifice a land". Read before the walk below because the non-mana
        # offer needs it too, and asked of the same reader the rewrite and the
        # resolution use, so a card whose keyword this engine cannot read is
        # never labelled as having one.
        buyback = buyback_cost(card.oracle_text or "")
        # …and which is its **kicker** (CR 702.33a), for the same reason: the
        # player deciding whether to pay {1}{G} on Benalish Emissary needs to
        # know that price is what destroys the land.
        #
        # Every one of them: a Battlemage prints two (CR 702.33b, "Kicker
        # {1}{G} and/or {2}{U}"), and each is an offer of its own with the
        # word beside its own symbols -- which is what tells the player the
        # two prices buy two different triggers.
        kickers = kicker_costs(card.oracle_text or "")
        charged = costs_charged_from(card, from_zone)
        # CR 601.2b's optional **non-mana** price (Constant Mists'
        # "Buyback—Sacrifice a land"). Emitted before the mana walk below and
        # before its early return, because a card printing only this one prints
        # no optional mana at all — and an offer nobody is shown is an offer
        # nobody can take, which for a buyback is the whole of the keyword.
        for cost in charged:
            if cost.optional_key is None:
                continue
            payable = self._unpayable_additional_cost(
                caster_index, card, (cost,),
                spell_hand_index=spell_hand_index, from_zone=from_zone,
                taken={cost.optional_key: 1},
            ) is None
            if payable and cost.mana_symbols and self.enforce_mana_costs:
                # "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's
                # Pet.) A price with a mana clause is payable only if the mana
                # is too — on top of the spell's own, out of the pool and the
                # untapped lands, which is the question the mana offers below
                # ask of themselves. The gate above cannot see it: CR 601.2h
                # leaves an unpayable *mana* cost to the payment, so without
                # this the prompt offered a kicker the cast then refused.
                wanted = dict(mana_cost_from_symbols(card.mana_cost or "") or {})
                for symbol, amount in cost.mana_cost.items():
                    wanted[symbol] = wanted.get(symbol, 0) + amount
                payable = plan_payment(
                    dict(caster.mana_pool),
                    untapped_mana_lands(self.controlled_by(caster_index)),
                    wanted, payer=caster,
                ) is not None
            offers.append({
                "kind": "optional_cost",
                # The same field name the mana offers carry, because it is the
                # same thing: the key ``optional_cost_payments`` is read back
                # by. The client's counter and ``_optional_cost_announcement``
                # both address an offer by it, so one name keeps them one path.
                "symbols": cost.optional_key,
                # "kicker" for "Kicker—Sacrifice a land" (Falling Timber), for
                # the reason the mana walk below names it: the player deciding
                # whether to give up a land needs to know that price is what
                # the spell's second sentence asks about.
                "label": (
                    "buyback" if buyback == cost.optional_key
                    else "kicker" if cost.optional_key in kickers
                    else cost.describe()
                ),
                "repeatable": False,
                # CR 601.2h through the gate itself rather than a second board
                # reading: an offer this shows as payable is one the cast will
                # accept, priced by the function that would refuse it.
                "max_times": 1 if payable else 0,
                "times": answered.get(cost.optional_key, 0),
            })

        every_offer = [
            offer
            for cost in charged
            for offer in cost.optional_mana
        ]
        if not every_offer:
            # Before reading the board at all: this runs for every card in every
            # hand on every poll, and all but three cards in the pool print no
            # optional mana cost.
            return offers
        pool = dict(caster.mana_pool)
        lands = untapped_mana_lands(self.controlled_by(caster_index))
        printed = mana_cost_from_symbols(card.mana_cost or "") or {}
        # ``buyback`` was read above, before the non-mana offers that also need
        # it. Worthy Cause is why the word survives to the prompt at all: it
        # prints a buyback *and* a mandatory sacrifice, and "Pay {2}" beside
        # "sacrifice a creature" says nothing about which price buys the card
        # back.
        for offer in every_offer:
            # An offer printing an {X} ("Kicker {X}{2}") is priced at X = 0
            # here: whether it can be taken *at all*. How large an X it can then
            # carry is ``max_x`` on the spec, asked once it is taken.
            one = offer.cost_at(0)
            # What the rest of the announcement has already claimed, so the
            # ceilings cannot each promise the same mana.
            floor = dict(printed)
            for other in every_offer:
                if other.symbols == offer.symbols:
                    continue
                for symbol, amount in other.cost.items():
                    floor[symbol] = floor.get(symbol, 0) + amount * answered.get(
                        other.symbols, 0
                    )
            reachable = sum(pool.values()) + len(lands)
            ceiling = (
                max(1, reachable // max(1, total_pips(one))) if offer.repeatable else 1
            )
            payable = 0
            for times in range(ceiling, 0, -1):
                required = dict(floor)
                for symbol, amount in one.items():
                    required[symbol] = required.get(symbol, 0) + amount * times
                if plan_payment(pool, lands, required, payer=caster) is not None:
                    payable = times
                    break
            offers.append({
                "kind": "optional_mana",
                # The canonical spelling ``mana_cost_label`` produces, which is
                # the key ``optional_cost_payments`` is read back by -- so what
                # the browser sends and what ``cost_target_count`` counts are the
                # same string, however the card printed it.
                "symbols": offer.symbols,
                # The keyword's name when this offer is one, else the symbols —
                # which is what every offer carried before buyback existed, so
                # the three cards that print an ordinary "you may pay …" send a
                # byte-identical payload.
                "label": (
                    "buyback" if buyback and offer.symbols == buyback
                    else "kicker" if offer.symbols in kickers
                    else offer.symbols
                ),
                "repeatable": offer.repeatable,
                "max_times": payable,
                "times": answered.get(offer.symbols, 0),
            })
        return offers

    def _additional_cost_x_ceiling(
        self, caster_index: int, card: CardDefinition, *, from_zone: str,
        spell_hand_index: int | None = None,
        taken: dict[str, int] | None = None,
    ) -> int | None:
        """The largest X the printed additional costs of *card* leave payable,
        or None when no printed cost names one.

        CR 107.3a lets the caster announce any X; CR 601.2h then refuses the
        cast when the announcement prices a cost they cannot pay. So the
        announcement has a ceiling, and it is *not* the mana pool: Fire
        Covenant's X is paid in life (CR 119.4 caps a life payment at the life
        total) and Infernal Harvest's in Swamps (there is no fifth Swamp to
        return off a board of four). The picker reads it so the browser offers
        exactly the range ``_unpayable_additional_cost`` would accept -- the
        picker-and-gate pairing this engine keeps having to re-establish, here on
        the half where disagreement means a cast announced and then refused.

        The minimum across every X-bearing cost, because one cast pays all of
        them: a card printing "pay X life **and** return X Swamps" is priced by
        whichever runs out first. No card prints two today; the minimum is what
        makes that a fact about the pool rather than an assumption in the code.
        """
        caster = self.players[caster_index]
        charged = costs_charged_from(card, from_zone)
        # CR 601.2b's printed life prices are paid out of the same total, so
        # they are claimed before the announced one is offered a ceiling --
        # the arithmetic ``_unpayable_additional_cost``'s ``life_already_owed``
        # does one step later, for the same reason.
        fixed_life = sum(cost.pay_life for cost in charged)
        bounds: list[int] = []
        for cost in charged:
            if cost.pay_life_x:
                bounds.append(max(0, caster.life - max(0, fixed_life)))
            if cost.return_count_x:
                bounds.append(len(self._additional_cost_candidates(
                    caster_index, cost, giving_up="return",
                )))
            # "…exile **X** creature cards from your graveyard" (Haunting
            # Misery). The third resource, and the third enumeration read here
            # rather than re-derived: the picker offers exactly what
            # ``_unpayable_additional_cost`` accepts because both count through
            # ``_graveyard_exile_candidates``. Left out, the browser would offer
            # an unbounded X for a spell whose whole price is a graveyard.
            if cost.exile_graveyard_count_x:
                bounds.append(
                    len(self._graveyard_exile_candidates(caster_index, cost))
                )
            # "…, discard **X** cards." (Firestorm.) The fourth resource, and
            # the fourth enumeration read rather than re-derived: the picker
            # offers exactly what ``_unpayable_additional_cost`` accepts because
            # both count through ``_discard_cost_payers``. The spell itself is
            # excluded there (CR 601.2a puts it on the stack before its costs
            # are paid), so a hand of one card holding only Firestorm bounds X
            # at 0 rather than at 1.
            if cost.discard_count_x:
                bounds.append(len(self._discard_cost_payers(
                    caster_index, cost, spell_hand_index=spell_hand_index,
                )))
            # "…, **choose a number between 0 and 5**." (Liquid Fire.) Not a
            # resource at all: the ceiling is the top of the range the card
            # prints, the same number ``AdditionalCost.number_refusal`` refuses
            # anything above.
            if cost.choose_number is not None:
                bounds.append(cost.choose_number[1])
            # "Kicker **{X}**" (Verdeloth the Ancient). The fifth resource, and
            # the one that *is* mana -- but not the mana cost's, so the
            # browser's own pool arithmetic (which prices an {X} it can see in
            # the mana cost) has nothing to price. Asked of ``plan_payment``,
            # the matching the payment itself runs, against the printed cost
            # plus the offer at each X: the largest the pool and the untapped
            # lands can pay together. Only for an offer the announcement so far
            # has *taken* -- a declined kicker announces no X at all.
            for offer in cost.optional_mana:
                if not offer.x_count:
                    continue
                if int((taken or {}).get(offer.symbols, 0) or 0) <= 0:
                    continue
                bounds.append(self._optional_x_ceiling(caster_index, card, offer))
        return min(bounds) if bounds else None

    def _optional_x_ceiling(
        self, caster_index: int, card: CardDefinition, offer
    ) -> int:
        """The largest X *offer* is payable at, on top of *card*'s mana cost.

        Read against the printed cost for ``cast_cost_offers``' reason: a
        CR 601.2f increase in force makes the number optimistic, and an
        optimistic announcement is refused by the payment with nothing spent.

        Through ``payments_at``, every way the offer may be paid at that X:
        "no more than one mana of each color may be spent" on Emblazoned
        Golem's X makes the ceiling a count of the *colours* the board can
        reach rather than of its mana, and an X no choice of colours pays is
        not offered.
        """
        caster = self.players[caster_index]
        pool = dict(caster.mana_pool)
        lands = untapped_mana_lands(self.controlled_by(caster_index))
        printed = mana_cost_from_symbols(card.mana_cost or "") or {}
        reachable = sum(pool.values()) + len(lands)
        for x_value in range(reachable, -1, -1):
            for payment in offer.payments_at(x_value):
                required = dict(printed)
                for symbol, amount in payment.items():
                    required[symbol] = required.get(symbol, 0) + amount
                if plan_payment(pool, lands, required, payer=caster) is not None:
                    return x_value
        return 0
